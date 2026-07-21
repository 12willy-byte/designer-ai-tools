"""门洞统一访问层（假洞物理分层·方案 b：吸收分区语义但不改存储）。

door_details 扁平结构与 build_door_details 输出保持不变——假洞/降级洞
全部留痕可回溯（evidence 含 wide_arc_downgrade 等判定依据）；本模块是
唯一的口径定义点，全项目消费方必须经这里读取，不再各自过滤：

- get_doors(details, level)：door_details 级四级口径
    usable    布局/概念可用的真门位：type==door 且 confidence ≥0.6
    countable 预算工程量计数口径的语义全集：door + 门洞量级（≤1.2m）的 opening
              （无语义分级的输入 door_type 为空时维持原口径计入）。
              注意：这是 details 级语义全集；预算/布局实际樘数还要看洞口
              能否附着到房间墙面（extract_room_facts 的 250mm 附着），
              附着后子集由 counts_as_interior_door 判定，两模块同源；
    openings  全部已采信通行洞口：door + opening（不含 unverified）
    all       全量含留痕（unverified/降级洞原样保留，永不做物理删除）
- is_door_opening(op)：布局事实开口级"是门洞几何"判定（kind=="door"），
  用于缺门洞拦截/家具避让/动线/现场确认点——行为与既有读取完全一致；
- counts_as_interior_door(op)：开口级预算计数判定（与 countable 同规则），
  预算 _counts_as_interior_door 与布局摘要门数共用此口径，保证
  "预算门樘数 = 布局摘要门数"。
"""
DOOR_LEVELS = ("usable", "countable", "openings", "all")

_USABLE_MIN_CONFIDENCE = 0.6
# 与门宽物理先验（pdf_plan_reader._DOOR_LEAF_MAX_MM）同口径：
# ≤1.2m 的 opening 大概率要装门计入工程量；超宽为垭口/推拉门/飘窗面不计。
_INTERIOR_DOOR_MAX_WIDTH_MM = 1200


def _det_type(det):
    return det.get("type") or det.get("door_type")


def _det_width(det):
    try:
        return float(det.get("width_mm") or 0)
    except (TypeError, ValueError):
        return 0.0


def det_is_usable(det):
    """真门位：有门扇证据的 door 且置信度达标；无置信度字段的旧输入按可用计。"""
    if _det_type(det) != "door":
        return False
    conf = det.get("confidence")
    return conf is None or conf >= _USABLE_MIN_CONFIDENCE


def det_is_countable(det):
    """预算室内门工程量口径（door_details 级）。"""
    dtype = _det_type(det)
    if dtype in (None, "door"):
        return True
    if dtype == "opening" and _det_width(det) <= _INTERIOR_DOOR_MAX_WIDTH_MM:
        return True
    return False


def det_is_opening(det):
    """已采信通行洞口：door + opening（unverified 疑似误判不采信，仅 all 留痕）。"""
    return _det_type(det) in (None, "door", "opening")


def get_doors(door_details, level="usable"):
    """按四级口径读取 door_details。level 见模块 docstring；默认 usable。"""
    details = list(door_details or [])
    if level == "all":
        return details
    if level == "usable":
        return [d for d in details if det_is_usable(d)]
    if level == "countable":
        return [d for d in details if det_is_countable(d)]
    if level == "openings":
        return [d for d in details if det_is_opening(d)]
    raise ValueError("未知门洞口径 level：%r（可选 %s）" % (level, DOOR_LEVELS))


# ---------------------------------------------------------------- 开口级判定
# 布局/预算事实（extract_room_facts 的 wall openings，含 kind/door_type/
# width_mm）共用以下两个判定；语义规则与 details 级一致，只是字段名不同。

def is_door_opening(op):
    """门洞几何判定（布局读取点专用）：事实开口中 kind=="door" 的条目。

    覆盖 door/opening/unverified 全部语义（它们在事实里都是 door 几何），
    与既有 op["kind"]=="door" 读取行为完全一致——家具避让/动线/缺门洞
    拦截需要全部通行洞口，不做语义过滤。
    """
    return op.get("kind") == "door"


def opening_matches_kind(op, kind):
    """开口类型匹配的统一入口：door 走 is_door_opening，其余按 kind 直判。"""
    if kind == "door":
        return is_door_opening(op)
    return op.get("kind") == kind


def counts_as_interior_door(op):
    """预算室内门工程量口径（开口级，与 det_is_countable 同规则）：

    - 有门扇证据的 door → 计入；
    - 门洞量级（≤1.2m）的 opening → 大概率要装门，计入；
    - 超宽 opening（推拉门/垭口/飘窗面）与 unverified（疑似误判）→ 不计；
    - 无语义分级的输入（扫描/手动/DXF，door_type 为空）维持原口径全部计入。
    """
    if op.get("kind") != "door":
        return False
    dtype = op.get("door_type")
    if dtype in (None, "door"):
        return True
    if dtype == "opening":
        try:
            return float(op.get("width_mm") or 0) <= _INTERIOR_DOOR_MAX_WIDTH_MM
        except (TypeError, ValueError):
            return False
    return False
