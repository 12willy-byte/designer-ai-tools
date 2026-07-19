"""
Step 2: 色彩方案生成器 (v2)
使用统一 AI 客户端
"""
import json, os, sys, re
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from core.ai_client import get_client
from core.design_schema import normalize_conditions

SYSTEM_PROMPT = """你是中国顶尖的室内设计色彩专家。根据客户需求，推荐专业的配色方案。

严格按 JSON 格式输出（只输出 JSON 不要多余文字）：
{
  "scheme_name": "方案名称",
  "description": "色彩方案说明（30字内）",
  "base_color": {"name":"主色名","hex":"#HEX","rgb":[R,G,B],"ratio":60,"usage":"墙面、大面积地面"},
  "secondary_color": {"name":"辅色名","hex":"#HEX","rgb":[R,G,B],"ratio":30,"usage":"家具、窗帘"},
  "accent_color": {"name":"点缀色名","hex":"#HEX","rgb":[R,G,B],"ratio":10,"usage":"抱枕、装饰品"},
  "wood_tone": "木色建议",
  "room_suggestions": [{"room":"客厅","base":"#HEX","accent":"#HEX","note":"说明"}]
}"""


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def generate_color_palette(conditions_json_path: str) -> dict:
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = normalize_conditions(json.load(f))

    style = conditions.get("style", {})
    space = conditions.get("space_data", {})

    prompt = "请为以下项目推荐色彩方案：\n\n"
    prompt += "风格: %s\n" % style.get("primary_style", "未指定")
    prompt += "色调: %s\n" % style.get("color_tone", "未指定")
    prompt += "设计关键词: %s\n" % style.get("keywords", "")
    if space.get("rooms"):
        prompt += "空间: %s\n" % ", ".join(r["name"] for r in space["rooms"])

    client = get_client()
    data = client.chat_json(SYSTEM_PROMPT, prompt, temperature=0.6, max_tokens=2000)

    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    os.makedirs(out_dir, exist_ok=True)

    img_path = render_palette_card(data, out_dir)
    data["palette_image"] = img_path
    with open(os.path.join(out_dir, "色彩方案色板.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def render_palette_card(data: dict, output_dir: str) -> str:
    width, height = 1200, 600
    img = Image.new("RGB", (width, height), "#F5F5F5")
    draw = ImageDraw.Draw(img)

    try:
        font_l = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 36)
        font_m = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 24)
        font_s = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
    except Exception:
        font_l = font_m = font_s = ImageFont.load_default()

    draw.text((40, 30), data.get("scheme_name", "色彩方案"), fill="#333", font=font_l)
    if data.get("description"):
        draw.text((40, 78), data["description"], fill="#888", font=font_m)

    colors = [
        ("主色 60%", data.get("base_color", {})),
        ("辅色 30%", data.get("secondary_color", {})),
        ("点缀色 10%", data.get("accent_color", {})),
    ]
    y0, bw, bh, gap, x0 = 140, 320, 120, 30, 60
    for i, (label, cd) in enumerate(colors):
        x = x0 + i * (bw + gap)
        try:
            rgb = hex_to_rgb(cd.get("hex", "#CCCCCC"))
        except Exception:
            rgb = (200, 200, 200)
        draw.rectangle([x, y0, x + bw, y0 + bh], fill=rgb, outline="#DDD")
        draw.text((x, y0 - 30), label, fill="#666", font=font_m)
        draw.text((x, y0 + bh + 8), cd.get("name", ""), fill="#333", font=font_m)
        draw.text((x, y0 + bh + 36), cd.get("hex", ""), fill="#999", font=font_s)
        usage = cd.get("usage", "")
        if usage:
            draw.text((x, y0 + bh + 58), usage[:22], fill="#888", font=font_s)

    path = os.path.join(output_dir, "色彩方案.png")
    img.save(path)
    return path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    result = generate_color_palette(inp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
