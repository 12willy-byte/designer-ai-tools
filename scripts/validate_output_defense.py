"""Offline validation for the unified AI output defense layer (chat_json 通道).

Covers (全部离线，注入 mock 坏输出，不触网):
A. 归一化修复：纯字符串材质槽位 / markdown 代码块 / 数组包装单对象 /
   缺键补默认 / 数字字符串转数值——修复成功且 repair_log 逐条留痕。
B. 安全降级：输出彻底无 JSON 时返回 fallback + ai_degraded_note 标注，
   任务不崩（不抛异常）。
C. demo 模式同通道：AI_DEMO_MODE=1 的 mock 输出过同一契约路径且结构完整。
D. 收口验证：step3 材质契约下坏槽位数据经统一层修复后可直接渲染
   （render_material_board 不再依赖点状防御 _as_material）。

Run: AI_DEMO_MODE=1 python3 scripts/validate_output_defense.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

os.environ["AI_DEMO_MODE"] = "1"

from core.ai_client import AIClient  # noqa: E402
from core.output_defense import (  # noqa: E402
    REPAIR_LOG, defend, get_repair_log, parse_loose_json, reset_repair_log,
)

_FAILURES = []


def _fail(msg):
    _FAILURES.append(msg)


def _check(cond, msg):
    if not cond:
        _fail(msg)


def _client_returning(raw):
    """构造一个 chat 被替换为固定坏输出的 demo 客户端（离线注入）。"""
    client = AIClient(demo_mode=True)
    client.chat = lambda *a, **k: raw  # noqa: E731 - 测试注入
    return client


CONTRACT = {
    "design_concept": "str",
    "materials": [{
        "room": "str",
        "floor": "object:type",
        "wall": "object:type",
        "feature_wall": "object:type",
        "ceiling": "object:type",
        "notes": "str",
    }],
    "global_recommendations": "object",
    "assumptions": "list",
    "budget_hint": "number",
}


def scenario_str_slot():
    """A1: 材质槽位返回纯字符串 → 包装为 {"type": ...} 并留痕 str_wrapped。"""
    raw = json.dumps({
        "design_concept": "测试",
        "materials": [{"room": "客厅", "floor": "木地板",
                       "wall": {"type": "乳胶漆"}, "notes": "n"}],
        "assumptions": "假设：单条字符串应被包装成列表",
        "budget_hint": "280000",
    }, ensure_ascii=False)
    reset_repair_log()
    data = _client_returning(raw).chat_json("测试", contract=CONTRACT,
                                            context="test_str_slot")
    mat = data["materials"][0]
    _check(isinstance(mat["floor"], dict) and mat["floor"].get("type") == "木地板",
           "str slot should wrap to {'type': '木地板'}, got %r" % (mat["floor"],))
    _check(isinstance(mat["wall"], dict) and mat["wall"].get("type") == "乳胶漆",
           "dict slot should pass through")
    _check(isinstance(mat["ceiling"], dict), "missing slot should default to {}")
    _check(isinstance(data["assumptions"], list) and len(data["assumptions"]) == 1,
           "str should wrap into list")
    _check(data["budget_hint"] == 280000 and isinstance(data["budget_hint"], int),
           "number string should convert to int")
    actions = {e["action"] for e in get_repair_log()}
    _check("str_wrapped" in actions, "repair_log should record str_wrapped")
    _check("number_str_converted" in actions,
           "repair_log should record number_str_converted")
    _check("missing_key" in actions, "repair_log should record missing_key")
    return {"repairs": len(get_repair_log()), "actions": sorted(actions)}


def scenario_markdown_and_array_wrap():
    """A2: markdown 代码块 + 数组包装单对象 → 剥离并取首元素。"""
    raw = ("好的，这是您要的方案：\n```json\n"
           + json.dumps([{"design_concept": "数组包了一层",
                          "materials": [], "assumptions": []}],
                        ensure_ascii=False)
           + "\n```\n希望对您有帮助。")
    reset_repair_log()
    data = _client_returning(raw).chat_json("测试", contract=CONTRACT,
                                            context="test_md_array")
    _check(isinstance(data, dict), "markdown-wrapped array should unwrap to dict")
    _check(data.get("design_concept") == "数组包了一层",
           "array-wrapped single object should take first element")
    actions = {e["action"] for e in get_repair_log()}
    _check("list_unwrapped" in actions, "repair_log should record list_unwrapped")
    return {"repairs": len(get_repair_log())}


def scenario_total_garbage():
    """B: 彻底无 JSON → fallback + ai_degraded_note，不抛异常。"""
    reset_repair_log()
    fallback = {"design_concept": "规则兜底方案", "materials": [], "assumptions": []}
    try:
        data = _client_returning("抱歉，我无法生成方案，请稍后再试。").chat_json(
            "测试", contract=CONTRACT, fallback=fallback,
            context="test_garbage")
    except Exception as exc:  # noqa: BLE001
        _fail("garbage output must not raise, got %r" % exc)
        return {}
    _check(data.get("design_concept") == "规则兜底方案",
           "fallback content should be used")
    _check(data.get("ai_degraded_note") == "AI 输出异常，已降级为规则生成",
           "degraded product should carry ai_degraded_note")
    actions = {e["action"] for e in get_repair_log()}
    _check("parse_failed" in actions and "fallback_used" in actions,
           "repair_log should record parse_failed + fallback_used")
    # 无 fallback 时也不崩
    data2 = _client_returning("（乱码）@@@").chat_json("测试", contract=CONTRACT,
                                                      context="test_garbage2")
    _check(isinstance(data2, dict) and data2.get("ai_degraded_note"),
           "no-fallback degradation should return empty structure with note")
    return {"repairs": len(get_repair_log())}


def scenario_demo_channel():
    """C: demo mock 输出过同一契约通道，结构完整（离线验收覆盖契约路径）。"""
    reset_repair_log()
    client = AIClient(demo_mode=True)
    data = client.chat_json("请生成材质方案", contract=CONTRACT,
                            context="test_demo_channel")
    _check(data.get("demo") is True, "demo mock should pass through with demo flag")
    mat = (data.get("materials") or [{}])[0]
    _check(isinstance(mat.get("floor"), dict) and mat["floor"].get("type"),
           "demo material slot should stay a dict with type")
    _check(isinstance(data.get("assumptions"), list),
           "demo assumptions should stay a list")
    return {"demo_channel_ok": True, "repairs": len(get_repair_log())}


def scenario_render_after_defense():
    """D: 坏槽位经统一层修复后，step3 渲染可直接消费（点状防御已收口）。"""
    raw = json.dumps({
        "design_concept": "收口验证",
        "materials": [{"room": "主卧", "floor": "橡木地板", "wall": "乳胶漆",
                       "feature_wall": {"type": "木饰面"},
                       "ceiling": {"type": "乳胶漆", "color": "白"}}],
        "global_recommendations": {},
        "assumptions": [],
    }, ensure_ascii=False)
    reset_repair_log()
    data = _client_returning(raw).chat_json("测试", contract=CONTRACT,
                                            context="test_render")
    from modules.m2_concept_design.step3_material_board import render_material_board
    with tempfile.TemporaryDirectory() as tmp:
        try:
            img = render_material_board(data, tmp)
        except AttributeError as exc:
            _fail("render should survive repaired data without point defenses: %r" % exc)
            return {}
        _check(os.path.exists(img), "material board image should be written")
    return {"render_ok": True, "repairs": len(get_repair_log())}


def scenario_parse_loose_json():
    """补充：松散解析对顶层数组、尾部解说的容忍。"""
    arr = parse_loose_json('输出如下：[{"a": 1}] 以上。')
    _check(isinstance(arr, list) and arr[0].get("a") == 1,
           "loose parse should extract top-level array")
    obj = parse_loose_json('前言 {"a": {"b": [1, 2]}} 后记')
    _check(obj.get("a", {}).get("b") == [1, 2], "loose parse should find balanced block")
    try:
        parse_loose_json("完全不是 JSON")
        _check(False, "garbage should raise ValueError in parse_loose_json")
    except ValueError:
        pass
    return {"parse_ok": True}


def main():
    results = {
        "str_slot_repair": scenario_str_slot(),
        "markdown_and_array_wrap": scenario_markdown_and_array_wrap(),
        "total_garbage_degradation": scenario_total_garbage(),
        "demo_mode_same_channel": scenario_demo_channel(),
        "render_after_defense": scenario_render_after_defense(),
        "parse_loose_json": scenario_parse_loose_json(),
    }
    ok = not _FAILURES
    print(json.dumps({
        "ok": ok,
        "failures": _FAILURES,
        "results": results,
    }, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
