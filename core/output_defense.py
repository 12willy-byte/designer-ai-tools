# -*- coding: utf-8 -*-
"""AI 结构化输出统一防御层（chat_json 通道）。

原则：模型输出不符合调用方声明的契约时——
1. 尽力归一化修复（常见漂移模式，见 normalize 的规则清单）；
2. 修不了就安全降级为调用方提供的 fallback 或空结构，绝不抛异常崩掉任务；
3. 每一次修复/降级都写入会话级 repair_log，可随产物留痕追溯
   （对齐项目"诚实留痕"哲学：manifest/独立文件都能看到 AI 输出到底被改过什么）。

契约写法（轻量，无第三方依赖）：
    {
        "materials": [{"room": "str", "floor": "object:type"}],   # 单元素 list = 列表项契约
        "assumptions": "list",                                     # 类型标签
        "budget_total": "number",
        "note": "str",
    }
类型标签：object / object:<str兜底字段> / list / str / number / any；
dict 表示对象逐键契约；[x] 表示元素符合 x 的列表。
"""
import copy
import json
import re
import time

SCHEMA_VERSION = "ai_repair_log.v1"

# 会话级修复/降级事件日志。进程内全局收集；流水线结束时可落盘
# （mvp_pipeline 写 concept_output/ai_repair_log.json）。
REPAIR_LOG = []


def reset_repair_log():
    REPAIR_LOG.clear()


def get_repair_log():
    return list(REPAIR_LOG)


def _log(context, path, action, detail):
    REPAIR_LOG.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context": context or "unknown",
        "path": path,
        "action": action,
        "detail": detail,
    })


def write_repair_log(path):
    """把当前会话的修复日志落盘（无事件时也写，便于确认"本次零修复"）。"""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_count": len(REPAIR_LOG),
        "events": get_repair_log(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------------
# 松散 JSON 解析：容忍 markdown 代码块、首尾解说文字、数组顶层
# ---------------------------------------------------------------------------
def parse_loose_json(raw):
    """从模型原始输出中提取 JSON（对象或数组）。失败抛 ValueError。"""
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    # markdown ```json ... ``` 代码块（对象或数组）
    match = re.search(r"```(?:json)?\s*([\{\[].*?[\}\]])\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 最外层平衡括号块：以最先出现的 { 或 [ 为准（谁先出现谁就是顶层），
    # 容忍尾部解说；内层括号不会抢先匹配。
    brackets = [(pos, pair) for pair in (("{", "}"), ("[", "]"))
                for pos in [raw.find(pair[0])] if pos != -1]
    brackets.sort(key=lambda item: item[0])
    for start, (open_ch, close_ch) in brackets[:1]:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("AI response did not contain JSON")


# ---------------------------------------------------------------------------
# 契约归一化
# ---------------------------------------------------------------------------
def _default_for(contract):
    if isinstance(contract, list):
        return []
    if isinstance(contract, dict):
        return {key: _default_for(sub) for key, sub in contract.items()}
    tag = str(contract).partition(":")[0]
    return {"object": {}, "list": [], "str": "", "number": 0}.get(tag)


def _to_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.replace(",", "").strip()
        try:
            num = float(text)
        except ValueError:
            return None
        return int(num) if num.is_integer() else num
    return None


def normalize(value, contract, path, context):
    """按契约把 value 归一化。所有修复动作写 repair_log，绝不抛异常。"""
    # 列表契约：[item_contract]
    if isinstance(contract, list):
        item_contract = contract[0] if contract else "any"
        if value is None:
            _log(context, path, "missing_key", "缺失，补默认空列表 []")
            return []
        if isinstance(value, dict):
            _log(context, path, "dict_wrapped_to_list", "单对象包装为列表")
            value = [value]
        elif not isinstance(value, list):
            _log(context, path, "scalar_wrapped_to_list",
                 "标量 %r 包装为列表" % (value,))
            value = [value]
        return [normalize(item, item_contract, "%s[%d]" % (path, i), context)
                for i, item in enumerate(value)]

    # 对象逐键契约：{key: sub_contract}
    if isinstance(contract, dict):
        if value is None:
            _log(context, path, "missing_key", "缺失，按契约补默认对象")
            value = {}
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                _log(context, path, "list_unwrapped", "数组包装的单对象，取首元素")
                value = value[0]
            else:
                _log(context, path, "object_degraded",
                     "期望对象，得到不可用列表，降级为空对象")
                value = {}
        elif not isinstance(value, dict):
            _log(context, path, "object_degraded",
                 "期望对象，得到 %s，降级为空对象" % type(value).__name__)
            value = {}
        out = dict(value)  # 契约外字段原样透传
        for key, sub in contract.items():
            out[key] = normalize(value.get(key), sub, "%s.%s" % (path, key), context)
        return out

    # 标签契约
    tag, _, field = str(contract).partition(":")
    if tag == "object":
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            _log(context, path, "list_unwrapped", "数组包装的单对象，取首元素")
            return value[0]
        if isinstance(value, str) and value.strip():
            _log(context, path, "str_wrapped",
                 "纯字符串包装为对象 {%s: 值}" % (field or "name"))
            return {field or "name": value.strip()}
        if value is None:
            _log(context, path, "missing_key", "缺失，补默认空对象 {}")
            return {}
        _log(context, path, "object_degraded",
             "期望对象，得到 %s，降级为空对象" % type(value).__name__)
        return {}
    if tag == "list":
        if isinstance(value, list):
            return value
        if value is None:
            _log(context, path, "missing_key", "缺失，补默认空列表 []")
            return []
        _log(context, path, "scalar_wrapped_to_list", "标量包装为列表")
        return [value]
    if tag == "str":
        if isinstance(value, str):
            return value
        if value is None:
            _log(context, path, "missing_key", "缺失，补默认空字符串")
            return ""
        if isinstance(value, (int, float)):
            _log(context, path, "number_to_str", "数值转字符串")
            return str(value)
        _log(context, path, "str_degraded",
             "期望字符串，得到 %s，降级为空字符串" % type(value).__name__)
        return ""
    if tag == "number":
        num = _to_number(value)
        if num is not None:
            if isinstance(value, str):
                _log(context, path, "number_str_converted",
                     "数字字符串 %r 转数值" % value)
            return num
        if value is None:
            _log(context, path, "missing_key", "缺失，补默认 0")
        else:
            _log(context, path, "number_degraded",
                 "期望数字，得到 %r，降级为 0" % (value,))
        return 0
    return value  # any / 未知标签：原样透传


def defend(data, contract, fallback=None, context=None):
    """chat_json 的统一出口：归一化 + 安全降级。

    - data 为 None（解析失败）或顶层类型与契约不符 → 使用 fallback
      （深拷贝）或空结构，并标注 ai_degraded_note；
    - 否则按契约归一化（契约外字段透传）。
    返回值保证与契约顶层同型（dict 契约 → dict；[x] 契约 → list）。
    """
    expects_list = isinstance(contract, list)
    if contract is None:
        # 未声明契约：只保证不返回完全不可用的非标量
        if data is None:
            _log(context, "$", "fallback_used", "未声明契约且解析失败，返回 fallback")
            if isinstance(fallback, (dict, list)):
                out = copy.deepcopy(fallback)
            else:
                out = [] if expects_list else {}
            if isinstance(out, dict):
                out["ai_degraded_note"] = "AI 输出异常，已降级为规则生成"
            return out
        return data

    top_ok = isinstance(data, list) if expects_list else isinstance(data, dict)
    if not top_ok and not expects_list:
        # dict 契约下的数组包装单对象（[{...}]）属于可修复漂移，
        # 交给 normalize 的 list_unwrapped 处理，不算顶层不可用。
        top_ok = (isinstance(data, list) and bool(data)
                  and isinstance(data[0], dict))
    if not top_ok:
        _log(context, "$", "fallback_used",
             "顶层结构不可用（%s），整体降级为 fallback" %
             ("解析失败" if data is None else type(data).__name__))
        if isinstance(fallback, (dict, list)):
            base = copy.deepcopy(fallback)
        else:
            base = [] if expects_list else {}
        degraded = True
    else:
        base = data
        degraded = False

    out = normalize(base, contract, "$", context)
    if degraded and isinstance(out, dict):
        out["ai_degraded_note"] = "AI 输出异常，已降级为规则生成"
    return out
