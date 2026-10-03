"""HTTP 请求 / 响应模型。

节点类型：
- source  水源
- sink    用水点
- junction 连接点

编号（id）为字符串，便于保留 "N01" 这类业务编号；排序时按字符串字典序。
"""
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, StrictInt, model_validator

NodeType = Literal["source", "sink", "junction"]


class NodeIn(BaseModel):
    id: str = Field(min_length=1, description="节点编号，唯一")
    type: NodeType
    name: str | None = Field(default=None, description="可选名称")


class PipeIn(BaseModel):
    id: str = Field(min_length=1, description="管段编号，唯一")
    # JSON 字段为 from/to（from 是 Python 关键字），Python 属性名为 from_node/to_node
    from_node: str = Field(min_length=1, validation_alias="from")
    to_node: str = Field(min_length=1, validation_alias="to")
    has_valve: bool = Field(default=False, description="该管段是否设有阀门")
    # 阀门初始状态：默认开启（未关闭）。非阀门管段传 true 会在导入时被拒绝。
    valve_closed: bool = False
    name: str | None = None

    model_config = {"populate_by_name": True, "extra": "forbid"}


class ImportIn(BaseModel):
    nodes: list[NodeIn]
    pipes: list[PipeIn]


class PlanIn(BaseModel):
    """故障隔离预演 / 提交入参。"""

    fault_pipe_id: str = Field(min_length=1, description="故障管段编号")
    close_pipe_ids: list[str] = Field(
        default_factory=list, description="拟关闭的阀门管段编号列表"
    )
    version: int = Field(ge=0, description="读取管网时的版本号，空网为 0")


class RecommendIn(BaseModel):
    """关阀建议入参：只知道故障管段编号与已读版本。"""

    fault_pipe_id: str = Field(min_length=1, description="故障管段编号")
    version: int = Field(ge=0, description="读取管网时的版本号，空网为 0")


class SourceTargetIn(BaseModel):
    """单个水源的目标运行状态。"""

    source_id: str = Field(min_length=1, description="水源节点编号")
    running: bool = Field(description="目标运行状态：true 恢复运行，false 停运")

    model_config = {"extra": "forbid"}


class SourceSwitchIn(BaseModel):
    """水源状态切换预演 / 确认入参：一批水源及各自目标运行状态 + 已读版本。"""

    targets: list[SourceTargetIn] = Field(
        min_length=1, description="水源编号与目标运行状态列表（同批编号不得重复）"
    )
    version: int = Field(ge=0, description="读取管网时的版本号，空网为 0")


class DeliverySourceIn(BaseModel):
    """单个水源的供水上限（非负整数升/小时；停运水源不供水，仍须列出）。"""

    source_id: str = Field(min_length=1, description="水源节点编号")
    # 流量均为非负整数：StrictInt 拒绝 true/false 等非整数类型（类型错误整体拒绝）
    capacity: StrictInt = Field(ge=0, description="供水上限（非负整数，升/小时）")

    model_config = {"extra": "forbid"}


class DeliveryPipeIn(BaseModel):
    """单条管段的双向共用输水上限（两方向合计不得超过该值）。"""

    pipe_id: str = Field(min_length=1, description="管段编号")
    capacity: StrictInt = Field(
        ge=0, description="双向共用输水上限（非负整数，升/小时）"
    )

    model_config = {"extra": "forbid"}


class DeliveryDemandIn(BaseModel):
    """单个用水点的最低流量需求（未列出的用水点不消耗流量）。"""

    sink_id: str = Field(min_length=1, description="用水点节点编号")
    demand: StrictInt = Field(ge=0, description="最低流量需求（非负整数，升/小时）")

    model_config = {"extra": "forbid"}


class DeliveryEvaluateIn(BaseModel):
    """流量核算入参：已读版本 + 每个水源供水上限 + 每条管段双向共用上限 + 用水点需求。

    水源与管段编号须完整覆盖当前管网（不多不少、同类不重复）；
    用水点编号须存在且为 sink；需求列表非空（允许单点需求为 0）。
    """

    version: StrictInt = Field(ge=0, description="读取管网时的版本号，空网为 0")
    sources: list[DeliverySourceIn] = Field(
        description="每个水源的供水上限（须覆盖当前管网全部水源；空网为空列表）"
    )
    pipes: list[DeliveryPipeIn] = Field(
        description="每条管段的双向共用输水上限（须覆盖全部管段；空网为空列表）"
    )
    demands: list[DeliveryDemandIn] = Field(
        description="非空用水点需求列表（未列需求的用水点不消耗流量）；"
        "为空时由领域校验统一返回 DELIVERY_DEMANDS_EMPTY"
    )


class DeliveryAllocationDemandIn(BaseModel):
    """保障等级分档交付中的单个用水点需求（未列出的用水点按零需求、不参与分配）。"""

    sink_id: str = Field(min_length=1, description="用水点节点编号")
    demand: StrictInt = Field(ge=0, description="需求流量（非负整数，升/小时；交付不超过需求）")
    # 保障等级：正整数，数字越小越优先（StrictInt 拒绝布尔/小数）
    level: StrictInt = Field(ge=1, description="保障等级（正整数，数字越小越优先）")

    model_config = {"extra": "forbid"}


class DeliveryAllocateIn(BaseModel):
    """保障等级分档交付入参。

    水源与管段编号须完整覆盖当前管网（不多不少、同类不重复）；
    用水点编号须存在且为 sink、同批不重复；需求列表非空；
    等级为正整数，数字越小越优先。先按等级依次最大化该等级交付总量，
    再在各等级总量最优条件下按（等级, 用水点编号）逐点最大化交付。
    """

    version: StrictInt = Field(ge=0, description="读取管网时的版本号，空网为 0")
    sources: list[DeliverySourceIn] = Field(
        description="每个水源的供水上限（须覆盖当前管网全部水源；空网为空列表）"
    )
    pipes: list[DeliveryPipeIn] = Field(
        description="每条管段的双向共用输水上限（须覆盖全部管段；空网为空列表）"
    )
    demands: list[DeliveryAllocationDemandIn] = Field(
        description="非空用水点需求列表（sink_id/demand/level）；"
        "未列需求的用水点按零需求、不参与分配"
    )


# ---------------------------------------------------------------- 响应模型


class NodeOut(BaseModel):
    id: str
    type: NodeType
    name: str | None = None
    # 仅水源节点有意义：true=运行中，false=已停运；非水源节点恒为 true
    running: bool = True


class PipeOut(BaseModel):
    id: str
    # 出参 JSON 键名为 from/to；Python 属性使用 from_/to_
    from_: str = Field(serialization_alias="from")
    to_: str = Field(serialization_alias="to")
    has_valve: bool
    valve_closed: bool | None = None
    name: str | None = None


class ImportOut(BaseModel):
    version: int
    node_count: int
    pipe_count: int
    # 整网导入在同一事务内冻结的状态快照编号（增量字段，旧客户端可忽略）
    snapshot_id: int | None = None


class NetworkOut(BaseModel):
    version: int
    updated_at: datetime | None = None
    nodes: list[NodeOut]
    pipes: list[PipeOut]


class IssueOut(BaseModel):
    code: str
    message: str
    pipe_id: str | None = None


class PreviewOut(BaseModel):
    version: int
    version_match: bool
    fault_pipe_id: str
    close_pipe_ids: list[str]
    isolatable: bool
    affected_sink_ids: list[str]
    issues: list[IssueOut]


class RecommendReasonOut(BaseModel):
    code: str
    message: str
    pipe_id: str | None = None


class RecommendOut(BaseModel):
    version: int
    version_match: bool
    fault_pipe_id: str
    feasible: bool
    recommended_close_pipe_ids: list[str]
    affected_sink_ids: list[str]
    reason: RecommendReasonOut | None = None


class SubmitOut(BaseModel):
    version: int
    fault_pipe_id: str
    closed_pipe_ids: list[str]
    affected_sink_ids: list[str]
    event_id: int
    snapshot_id: int | None = None


class RestoreIn(BaseModel):
    """复供预演 / 确认入参：按隔离事件编号与当前管网版本操作。"""

    version: int = Field(ge=0, description="读取管网时的版本号，空网为 0")


class ReopenBlockOut(BaseModel):
    code: str
    message: str
    pipe_id: str | None = None
    reachable_endpoints: list[str] = []


class RestorePreviewOut(BaseModel):
    version: int
    version_match: bool
    event_id: int
    status: str
    fault_pipe_id: str
    closed_pipe_ids: list[str]
    safe: bool
    restored_sink_ids: list[str]
    block_reasons: list[ReopenBlockOut]


class RestoreOut(BaseModel):
    version: int
    event_id: int
    status: str
    fault_pipe_id: str
    reopened_pipe_ids: list[str]
    restored_sink_ids: list[str]
    snapshot_id: int | None = None


class SourceTargetOut(BaseModel):
    source_id: str
    running: bool


class SourceSwitchPreviewOut(BaseModel):
    version: int
    version_match: bool
    changed: bool
    safe: bool
    targets: list[SourceTargetOut]
    affected_sink_ids: list[str]
    restored_sink_ids: list[str]
    block_reasons: list[ReopenBlockOut]
    issues: list[IssueOut]


class SourceSwitchOut(BaseModel):
    version: int
    changed: bool
    targets: list[SourceTargetOut]
    affected_sink_ids: list[str]
    restored_sink_ids: list[str]
    # 仅在确有状态变化时产生快照；全部目标状态已满足（changed=false）时为 null
    snapshot_id: int | None = None


class DeliveryEvaluateOut(BaseModel):
    """流量核算只读结果：当前版本/版本是否匹配/需求总量/最大可交付总量/能否全部满足。"""

    version: int
    version_match: bool
    total_demand: int
    max_delivered_total: int
    feasible: bool


class SinkDeliveryOut(BaseModel):
    """单个用水点的分档交付：需求、实际交付与缺口。"""

    sink_id: str
    level: int
    demand: int
    delivered: int
    shortfall: int
    satisfied: bool


class LevelDeliveryOut(BaseModel):
    """单个保障等级的交付汇总（按等级数值升序）。"""

    level: int
    demand: int
    delivered: int
    shortfall: int
    all_satisfied: bool


class DeliveryAllocateOut(BaseModel):
    """保障等级分档交付只读结果。

    先按等级依次最大化该等级交付总量，再在各等级总量最优条件下按
    （等级, 用水点编号）逐点最大化交付；deliveries 按该顺序排列，
    各点交付由一组同时可行的整数流量实现。
    """

    version: int
    version_match: bool
    total_demand: int
    total_delivered: int
    all_satisfied: bool
    levels: list[LevelDeliveryOut]
    deliveries: list[SinkDeliveryOut]


class ReconcileSourceIn(BaseModel):
    """单个水源的实际注入量（非负整数升/小时；停运水源注入必须为 0，仍须列出）。"""

    source_id: str = Field(min_length=1, description="水源节点编号")
    injection: StrictInt = Field(ge=0, description="实际注入量（非负整数，升/小时）")

    model_config = {"extra": "forbid"}


class ReconcileSinkIn(BaseModel):
    """单个用水点的实际取用量（非负整数升/小时；未取用按 0 申报，仍须列出）。"""

    sink_id: str = Field(min_length=1, description="用水点节点编号")
    withdrawal: StrictInt = Field(ge=0, description="实际取用量（非负整数，升/小时）")

    model_config = {"extra": "forbid"}


class ReconcilePipeIn(BaseModel):
    """单条管段的双向共用容量与可为空的带符号读数。

    读数以管段 from→to 为正（升/小时）；null 表示该管段缺报，由服务推断
    全部可行解中的最小/最大流量。
    """

    pipe_id: str = Field(min_length=1, description="管段编号")
    capacity: StrictInt = Field(
        ge=0, description="双向共用容量（非负整数，升/小时）"
    )
    # 带符号读数允许负数（to→from 方向）；StrictInt 拒绝布尔/小数（非整数整体拒绝）
    reading: StrictInt | None = Field(
        default=None,
        description="带符号流量计读数（from→to 为正）；null/缺省表示缺报",
    )

    model_config = {"extra": "forbid"}


class MeterReconcileIn(BaseModel):
    """读数核对入参：已读版本 + 每个水源实际注入量 + 每个用水点实际取用量
    + 覆盖全部管段的双向共用容量与可为空带符号读数。

    三类编号均须完整覆盖当前管网（不多不少）、同类不得重复；
    注入、取用、容量均为非负整数升/小时；读数为带符号整数或 null。
    """

    version: StrictInt = Field(ge=0, description="读取管网时的版本号，空网为 0")
    sources: list[ReconcileSourceIn] = Field(
        description="每个水源的实际注入量（须覆盖全部水源；空网为空列表）"
    )
    sinks: list[ReconcileSinkIn] = Field(
        description="每个用水点的实际取用量（须覆盖全部用水点；空网为空列表）"
    )
    pipes: list[ReconcilePipeIn] = Field(
        description="每条管段的双向共用容量与可为空带符号读数（须覆盖全部管段）"
    )


class ReconcileReasonOut(BaseModel):
    code: str
    message: str
    pipe_id: str | None = None
    node_id: str | None = None


class MeterReadingRangeOut(BaseModel):
    """单条缺报管段在全部可行解中的流量范围（带符号，from→to 为正）。"""

    pipe_id: str
    # 出参保留管段方向，便于调度员核对符号含义
    from_: str = Field(serialization_alias="from")
    to_: str = Field(serialization_alias="to")
    min_flow: int
    max_flow: int
    # min_flow == max_flow：缺报读数可唯一确定
    determinable: bool


class MeterReconcileOut(BaseModel):
    """读数核对结果：当前版本/版本是否匹配/是否一致/缺报管段可行流量范围。

    consistent=false（无可行解或硬约束被违反）时 readings 恒为空列表，
    原因见 reasons；版本过期不拒绝，仍按当前状态计算，仅 version_match=false。
    """

    version: int
    version_match: bool
    consistent: bool
    readings: list[MeterReadingRangeOut]
    reasons: list[ReconcileReasonOut]


class EventOut(BaseModel):
    id: int
    version_before: int
    version_after: int
    fault_pipe_id: str
    closed_pipe_ids: list[str]
    affected_sink_ids: list[str]
    status: str = "open"
    restored_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------- 状态快照


class SnapshotNodeOut(BaseModel):
    id: str
    type: NodeType
    name: str | None = None
    running: bool = True


class SnapshotPipeOut(BaseModel):
    id: str
    from_: str = Field(serialization_alias="from")
    to_: str = Field(serialization_alias="to")
    has_valve: bool
    valve_closed: bool
    name: str | None = None


class SnapshotFaultOut(BaseModel):
    event_id: int
    fault_pipe_id: str


class SnapshotStateOut(BaseModel):
    """操作后冻结的完整供水状态（历史只读，绝不以后续状态回填）。"""

    nodes: list[SnapshotNodeOut]
    pipes: list[SnapshotPipeOut]
    open_faults: list[SnapshotFaultOut]
    supplied_sink_ids: list[str]


class SnapshotOut(BaseModel):
    """单条状态快照：编号 + 操作类型 + 当时管网版本 + 关联事件编号 + 冻结状态。"""

    id: int
    op_type: str
    network_version: int
    event_id: int | None = None
    state: SnapshotStateOut
    created_at: datetime


class SnapshotMetaOut(BaseModel):
    """快照列表项：与详情一致（列表与详情均返回冻结状态，便于调度员直接回看）。"""

    id: int
    op_type: str
    network_version: int
    event_id: int | None = None
    state: SnapshotStateOut
    created_at: datetime


class SnapshotNodeChangeOut(BaseModel):
    id: str
    type: NodeType
    name: str | None = None
    running: bool = True


class SnapshotPipeChangeOut(BaseModel):
    id: str
    from_: str = Field(serialization_alias="from")
    to_: str = Field(serialization_alias="to")
    has_valve: bool
    valve_closed: bool
    name: str | None = None


class SnapshotNodeDiffOut(BaseModel):
    added: list[SnapshotNodeChangeOut]
    removed: list[SnapshotNodeChangeOut]


class SnapshotPipeDiffOut(BaseModel):
    added: list[SnapshotPipeChangeOut]
    removed: list[SnapshotPipeChangeOut]


class ValvePositionChangeOut(BaseModel):
    pipe_id: str
    valve_closed_before: bool
    valve_closed_after: bool


class ValvePositionDiffOut(BaseModel):
    changed: list[ValvePositionChangeOut]


class SourceStateChangeOut(BaseModel):
    source_id: str
    running_before: bool
    running_after: bool


class SourceStateDiffOut(BaseModel):
    changed: list[SourceStateChangeOut]


class SnapshotFaultDiffOut(BaseModel):
    added: list[SnapshotFaultOut]
    removed: list[SnapshotFaultOut]


class SuppliedSinksDiffOut(BaseModel):
    added: list[str]
    removed: list[str]


class SnapshotDiffOut(BaseModel):
    """相邻快照的六类净变化（节点/管段/阀位/水源状态/待修复故障/供水点）。"""

    base_snapshot_id: int | None
    target_snapshot_id: int
    base_network_version: int | None
    target_network_version: int
    nodes: SnapshotNodeDiffOut
    pipes: SnapshotPipeDiffOut
    valve_positions: ValvePositionDiffOut
    source_states: SourceStateDiffOut
    open_faults: SnapshotFaultDiffOut
    supplied_sinks: SuppliedSinksDiffOut


# ---------------------------------------------------------------- 有序操作演练（只读，多步）


class DrillIsolateStepIn(BaseModel):
    """演练步骤：隔离故障管段并关闭拟关阀门。"""

    type: Literal["isolate"]
    fault_pipe_id: str = Field(min_length=1, description="故障管段编号")
    close_pipe_ids: list[str] = Field(
        default_factory=list, description="拟关闭的阀门管段编号列表"
    )

    model_config = {"extra": "forbid"}


class DrillRestoreStepIn(BaseModel):
    """演练步骤：复供。

    event_id 引用现存隔离事件；temp_event_step 引用本次先前隔离步骤
    （从 1 开始的步骤序号）产生的临时事件；二者恰好给一个。
    """

    type: Literal["restore"]
    event_id: int | None = Field(
        default=None,
        ge=1,
        description="现存隔离事件编号（GET /api/isolation/events 中的 id）",
    )
    temp_event_step: int | None = Field(
        default=None,
        ge=1,
        description="本次先前隔离步骤的序号（从 1 开始），引用其临时事件",
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _exactly_one_ref(self):
        if (self.event_id is None) == (self.temp_event_step is None):
            raise ValueError(
                "复供步骤必须且只能给出 event_id 与 temp_event_step 中的一个"
            )
        return self


class DrillSourceSwitchStepIn(BaseModel):
    """演练步骤：一批水源切换到目标运行状态。"""

    type: Literal["source_switch"]
    targets: list[SourceTargetIn] = Field(
        min_length=1, description="水源编号与目标运行状态列表（同批编号不得重复）"
    )

    model_config = {"extra": "forbid"}


DrillStepIn = Annotated[
    Union[
        DrillIsolateStepIn,
        DrillRestoreStepIn,
        DrillSourceSwitchStepIn,
    ],
    Field(discriminator="type"),
]


class DrillSequenceIn(BaseModel):
    """有序隔离 / 复供 / 水源切换演练入参。

    以当前管网与已读版本为起点，在服务内存中按顺序逐步应用并校验；
    全程只读，不推进真实版本、不改阀位 / 水源状态 / 事件 / 快照。
    """

    version: StrictInt = Field(ge=0, description="读取管网时的版本号，空网为 0")
    steps: list[DrillStepIn] = Field(
        min_length=1, description="有序演练步骤（至少 1 步）"
    )


class DrillErrorOut(BaseModel):
    code: str
    message: str
    # 结构性问题明细（形态随 code 而变：PLAN_INVALID 为管段问题，
    # RESTORE_UNSAFE / SOURCE_SWITCH_UNSAFE 为含 reachable_endpoints 的风险明细）
    issues: list[dict] | None = None


class DrillEventRefOut(BaseModel):
    """复供步骤引用的事件：existing=现存事件，temporary=本次隔离产生的临时事件。"""

    kind: Literal["existing", "temporary"]
    event_id: int | None = None
    step_index: int | None = None


class DrillBlockReasonOut(BaseModel):
    code: str
    message: str
    pipe_id: str | None = None
    reachable_endpoints: list[str] = []


class DrillStepOut(BaseModel):
    """单步演练结果。

    status=applied 表示该步已应用到演练态；rejected 表示该步非法/不安全，
    为演练中的最后一步（后续步骤不再执行）。每步的 affected_sink_ids /
    restored_sink_ids 均相对上一步应用后的演练态计算。
    """

    index: int
    type: Literal["isolate", "restore", "source_switch"]
    status: Literal["applied", "rejected"]
    version: int | None = None
    error: DrillErrorOut | None = None
    affected_sink_ids: list[str] = []
    restored_sink_ids: list[str] = []
    # 隔离步骤
    fault_pipe_id: str | None = None
    close_pipe_ids: list[str] | None = None
    isolatable: bool | None = None
    temp_event_id: int | None = None
    event_ref: DrillEventRefOut | None = None
    issues: list[dict] | None = None
    # 复供步骤
    reopen_pipe_ids: list[str] | None = None
    safe: bool | None = None
    block_reasons: list[DrillBlockReasonOut] | None = None
    # 水源切换步骤
    targets: list[SourceTargetOut] | None = None
    changed: bool | None = None


class DrillTempEventOut(BaseModel):
    """本次隔离步骤产生的临时事件（负整数编号，演练结束即失效，不写库）。"""

    temp_event_id: int
    step_index: int
    fault_pipe_id: str
    closed_pipe_ids: list[str]
    restored: bool


class DrillValveOut(BaseModel):
    pipe_id: str
    has_valve: bool
    valve_closed: bool


class DrillOpenFaultOut(BaseModel):
    event_id: int
    fault_pipe_id: str
    # true=本次隔离产生的临时事件；false=现存待修复事件
    temporary: bool


class DrillFinalStateOut(BaseModel):
    """演练结束（或首个失败步骤的前一步）时的演练态。"""

    version: int
    running_source_ids: list[str]
    valves: list[DrillValveOut]
    open_faults: list[DrillOpenFaultOut]
    supplied_sink_ids: list[str]


class DrillFailureOut(BaseModel):
    """首个非法 / 不安全步骤（演练在此停止，后续步骤不再执行）。"""

    step_index: int
    code: str
    message: str
    issues: list[dict] | None = None


class DrillSequenceOut(BaseModel):
    """有序演练结果：逐步结果、临时事件引用与最终演练态。

    read_only 恒为 true：真实版本、阀位、水源状态、事件、快照均不变；
    失败时 final_state 为最后一次成功应用后的状态（不含失败步骤变更）。
    """

    version: int = Field(description="演练开始时读到的真实当前版本")
    version_match: bool
    status: Literal["ok", "rejected"]
    read_only: bool = True
    steps: list[DrillStepOut]
    failure: DrillFailureOut | None = None
    temp_events: list[DrillTempEventOut]
    final_state: DrillFinalStateOut
