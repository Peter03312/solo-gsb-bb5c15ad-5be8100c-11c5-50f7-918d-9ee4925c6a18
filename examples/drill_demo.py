#!/usr/bin/env python3
"""有序隔离 / 复供 / 水源切换演练全流程示例（全程只读，仅依赖标准库）。

用法：
    python3 examples/drill_demo.py [base_url]

默认 base_url 为 http://localhost:8000。

演示管网（examples/restore_network.json）：

    S --P1[阀]-- A --P2[阀]-- B --P4[阀]-- D --P6(无阀,故障1)-- U3
                   |                       |
                 P3[阀]                   P7(无阀,故障2)-- E --P8[阀]-- U4
                   |
                  U1

POST /api/ops/drill 以当前真实状态为起点，在服务内存中按顺序逐步应用
隔离 / 复供 / 水源切换，并对每一步套用与既有**提交**接口完全相同的校验
（故障两端须隔离；复供 / 恢复水源不得让任一待修复故障端点重新进水）。

脚本依次演示：
  1. 导入管网（真实版本 1）
  2. 成功演练：隔离 P6(关 P4) -> 隔离 P7(空方案) -> 复供临时事件2 ->
     复供临时事件1；逐步失供 / 恢复点相对上一步计算，临时事件用负整数编号
  3. 演练后确认真实版本 / 阀位 / 事件 / 快照全部未变（全程只读）
  4. 失败演练：先恢复外层临时事件会让待修复 P7 的 D 端重新进水，
     第 3 步 RESTORE_UNSAFE，停止后续演练，最终态不含失败步骤
  5. 版本过期：409 VERSION_CONFLICT 并返回当前版本
  6. 引用不存在的临时步骤：TEMP_EVENT_NOT_FOUND
  7. 真实提交一条隔离后，演练引用现存事件编号复供（existing 引用）
  8. 水源切换步骤混排（停运 / 恢复与隔离互相对待修复故障的影响）
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "BASE_URL", "http://localhost:8000"
)
SAMPLE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "restore_network.json"
)


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def show(title: str, status: int, body: dict) -> None:
    print(f"\n===== {title}（HTTP {status}）=====")
    print(json.dumps(body, ensure_ascii=False, indent=2))


def drill(steps: list[dict], version: int) -> tuple[int, dict]:
    return call("POST", "/api/ops/drill", {"version": version, "steps": steps})


def main() -> None:
    # 1. 导入演示管网（版本 1）
    with open(SAMPLE, "rb") as fh:
        network = json.loads(fh.read().decode())
    status, body = call("POST", "/api/network/import", network)
    show("1. 整网导入", status, body)
    assert status == 200 and body["version"] == 1

    # 2. 成功演练：两条叠加故障按“区内先复供、外层后复供”的安全顺序操作
    steps = [
        {"type": "isolate", "fault_pipe_id": "P6", "close_pipe_ids": ["P4"]},
        {"type": "isolate", "fault_pipe_id": "P7", "close_pipe_ids": []},
        # 复供引用本次先前隔离步骤的序号（从 1 开始）产生的临时事件
        {"type": "restore", "temp_event_step": 2},
        {"type": "restore", "temp_event_step": 1},
    ]
    status, body = drill(steps, version=1)
    show("2. 成功演练：隔离×2 → 按序复供临时事件×2", status, body)
    assert status == 200 and body["status"] == "ok"
    assert [s["version"] for s in body["steps"]] == [2, 3, 4, 5]
    assert body["steps"][0]["affected_sink_ids"] == ["U3", "U4"]
    assert body["steps"][3]["restored_sink_ids"] == ["U3", "U4"]
    assert [t["temp_event_id"] for t in body["temp_events"]] == [-1, -2]
    assert body["final_state"]["supplied_sink_ids"] == ["U1", "U3", "U4"]

    # 3. 全程只读：真实版本、阀位、事件、快照均未变
    status, net = call("GET", "/api/network")
    p4 = next(p for p in net["pipes"] if p["id"] == "P4")
    status2, events = call("GET", "/api/isolation/events")
    status3, snaps = call("GET", "/api/snapshots")
    print(
        "\n===== 3. 演练只读核对 =====\n"
        f"真实版本={net['version']}（仍为 1），P4 阀位关闭={p4['valve_closed']}，"
        f"真实事件数={len(events)}，快照类型={[s['op_type'] for s in snaps]}"
    )
    assert net["version"] == 1 and p4["valve_closed"] is False
    assert events == [] and [s["op_type"] for s in snaps] == ["network_import"]

    # 4. 失败演练：外层事件先复供 → 待修复 P7 的 D 端重新进水
    status, body = drill(
        [
            {"type": "isolate", "fault_pipe_id": "P6", "close_pipe_ids": ["P4"]},
            {"type": "isolate", "fault_pipe_id": "P7", "close_pipe_ids": []},
            {"type": "restore", "temp_event_step": 1},   # 不安全
            {"type": "restore", "temp_event_step": 2},   # 不会执行
        ],
        version=1,
    )
    show("4. 失败演练：复供顺序不安全（首个失败步骤即停止）", status, body)
    assert status == 200 and body["status"] == "rejected"
    assert body["failure"]["step_index"] == 3
    assert body["failure"]["code"] == "RESTORE_UNSAFE"
    assert len(body["steps"]) == 3  # 第 4 步不再演练
    # 最终态停在步骤 2 应用后：P4 仍关、两条临时故障仍待修复、演练版本 3
    assert body["final_state"]["version"] == 3
    assert {f["fault_pipe_id"] for f in body["final_state"]["open_faults"]} == {
        "P6", "P7"
    }

    # 5. 版本过期：拒绝演练并返回当前版本
    status, body = drill(
        [{"type": "isolate", "fault_pipe_id": "P6", "close_pipe_ids": ["P4"]}],
        version=99,
    )
    show("5. 版本过期：409 VERSION_CONFLICT", status, body)
    assert status == 409 and body["error"]["code"] == "VERSION_CONFLICT"
    assert body["error"]["current_version"] == 1

    # 6. 引用不存在的临时隔离步骤
    status, body = drill([{"type": "restore", "temp_event_step": 7}], version=1)
    show("6. 临时事件引用不存在：TEMP_EVENT_NOT_FOUND", status, body)
    assert body["status"] == "rejected"
    assert body["failure"]["code"] == "TEMP_EVENT_NOT_FOUND"

    # 7. 真实提交一条隔离，再在演练中用现存事件编号复供（不真正复供）
    status, body = call(
        "POST",
        "/api/isolation/submit",
        {"fault_pipe_id": "P6", "close_pipe_ids": ["P4"], "version": 1},
    )
    show("7a. 真实提交隔离（产生现存事件 1，真实版本 2）", status, body)
    assert status == 200 and body["event_id"] == 1
    status, body = drill([{"type": "restore", "event_id": 1}], version=2)
    show("7b. 演练引用现存事件 1 复供（existing；真实事件仍 open）", status, body)
    assert body["status"] == "ok"
    assert body["steps"][0]["event_ref"] == {
        "kind": "existing", "event_id": 1, "step_index": None
    }
    _, events = call("GET", "/api/isolation/events")
    assert events[0]["status"] == "open"  # 演练不改真实事件状态

    # 8. 水源切换混排：演练内先复供现存事件（撤掉对 P6 片区的隔离），
    #    再停运唯一水源 S（允许全网无运行水源，U1-U4 全部新增失供）
    status, body = drill(
        [
            {"type": "restore", "event_id": 1},
            {"type": "source_switch",
             "targets": [{"source_id": "S", "running": False}]},
        ],
        version=2,
    )
    show("8. 复供现存事件 + 停运水源混排演练", status, body)
    assert body["status"] == "ok"
    assert body["steps"][0]["restored_sink_ids"] == ["U3", "U4"]
    assert body["steps"][1]["affected_sink_ids"] == ["U1", "U3", "U4"]
    assert body["final_state"]["running_source_ids"] == []
    assert body["final_state"]["supplied_sink_ids"] == []

    print("\n全部演练场景通过；真实管网除步骤 7a 的一次真实提交外未发生其他变化。")


if __name__ == "__main__":
    main()
