"""Step 6: 空间氛围图生成器（通义万相）
自动为每个关键空间生成 AI 效果图
"""
import json, os, sys, time, re, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from core.ai_client import get_client
from core.design_schema import normalize_conditions
from modules.config import DASHSCOPE_API_KEY

# 需要生成氛围图的房间（默认）
DEFAULT_ROOMS = ["客厅", "主卧", "厨房", "餐厅"]


def load_context(conditions_path):
    """加载设计条件 + 已有概念输出"""
    with open(conditions_path, "r", encoding="utf-8") as f:
        conditions = normalize_conditions(json.load(f))

    base_dir = os.path.dirname(os.path.abspath(conditions_path))
    out_dir = os.path.join(base_dir, "concept_output")

    # 设计定位文案
    brief = ""
    brief_path = os.path.join(out_dir, "设计定位.txt")
    if os.path.exists(brief_path):
        brief = open(brief_path, "r", encoding="utf-8").read()

    return conditions, brief, out_dir


def generate_prompt(room_name, conditions, brief):
    """用 DeepSeek 为指定空间生成专业的生图 prompt"""
    style = conditions.get("style", {})
    space = conditions.get("space_data", {})
    rooms_req = conditions.get("rooms_requirements", {})

    prompt = "你是一个专业的室内设计 AI 生图提示词专家。请为一个空间生成高质量的通义万相生图提示词。\n\n"
    prompt += "项目风格: %s\n" % style.get("primary_style","现代简约")
    prompt += "色调: %s\n" % style.get("color_tone","中性色")
    prompt += "设计定位: %s\n\n" % brief[:200]
    prompt += "空间名称: %s\n" % room_name

    # 空间尺寸
    for rm in space.get("rooms", []):
        if rm["name"] == room_name:
            prompt += "空间尺寸: %d x %d mm (%.1f m2)\n" % (
                rm["width_mm"], rm["height_mm"], rm["area_m2"])

    # 该空间的设计需求
    req = rooms_req.get(room_name, {})
    if req:
        prompt += "客户需求:\n"
        for k, v in req.items():
            if v: prompt += "  %s: %s\n" % (k, v)

    prompt += "\n请输出一句中文生图提示词（50-80字），包含：空间类型、风格、色调、主要家具、材质、灯光氛围。"
    prompt += " 直接输出提示词内容，不要多余文字。"

    return get_client().chat(prompt, temperature=0.7, max_tokens=300).strip()


def generate_atmosphere(conditions_json_path, rooms=None):
    """为指定房间生成氛围图"""
    if rooms is None:
        rooms = DEFAULT_ROOMS

    conditions, brief, out_dir = load_context(conditions_json_path)
    if not DASHSCOPE_API_KEY:
        return [{
            "room": "all",
            "prompt": "",
            "image_path": "",
            "image_size": 0,
            "skipped": True,
            "reason": "DASHSCOPE_API_KEY is not configured",
        }]
    import dashscope
    dashscope.api_key = DASHSCOPE_API_KEY

    space = conditions.get("space_data", {})
    available_rooms = {rm["name"]: rm for rm in space.get("rooms", [])}

    results = []

    for room_name in rooms:
        if room_name not in available_rooms:
            print("  跳过 %s（不在空间数据中）" % room_name)
            continue

        print("  [%s] 生成生图提示词..." % room_name)
        prompt_text = generate_prompt(room_name, conditions, brief)
        print("    Prompt: %s" % prompt_text[:60])

        print("    调用通义万相...")
        resp = dashscope.ImageSynthesis.call(
            model="wanx-v1",
            prompt=prompt_text,
            n=1,
            size="1024*1024",
        )

        if resp.status_code == 200:
            url = resp.output.results[0].url
            filename = "%s氛围图.png" % room_name
            filepath = os.path.join(out_dir, filename)

            print("    下载图片...")
            urllib.request.urlretrieve(url, filepath)
            size = os.path.getsize(filepath)

            results.append({
                "room": room_name,
                "prompt": prompt_text,
                "image_path": filepath,
                "image_size": size,
            })
            print("    OK: %s (%d bytes)" % (filename, size))
        else:
            print("    失败: %s" % resp.message)

    return results


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    rooms = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    print("=== 氛围图生成 ===")
    results = generate_atmosphere(inp, rooms)
    print("\n=== 完成 ===")
    for r in results:
        print("  %s: %s" % (r["room"], r["image_path"]))


if __name__ == "__main__":
    main()
