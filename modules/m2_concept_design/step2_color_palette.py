"""Step 2: 色彩方案生成器"""
import json, os, sys, math
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

SYSTEM_PROMPT = """你是中国顶尖的室内设计色彩专家。根据客户需求，推荐专业的配色方案。

请按以下格式输出（严格遵循 JSON 格式，只输出 JSON 不要多余文字）：

{
  "scheme_name": "方案名称",
  "description": "色彩方案说明（30字内）",
  "base_color": {"name":"主色名","hex":"#HEX","rgb":[R,G,B],"ratio":60,"usage":"墙面、大面积地面"},
  "secondary_color": {"name":"辅色名","hex":"#HEX","rgb":[R,G,B],"ratio":30,"usage":"家具、窗帘"},
  "accent_color": {"name":"点缀色名","hex":"#HEX","rgb":[R,G,B],"ratio":10,"usage":"抱枕、装饰品"},
  "wood_tone": "木色建议",
  "room_suggestions": [
    {"room":"客厅","base":"#HEX","accent":"#HEX","note":"说明"}
  ],
  "alternative_schemes": [
    {"name":"备选1","description":"说明"}
  ]
}"""


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))


def generate_color_palette(conditions_json_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    style = conditions.get("style", {})
    space = conditions.get("space_data", {})
    special = conditions.get("special_requirements", {})

    prompt = "请为以下项目推荐色彩方案：\n\n"
    prompt += "风格: %s\n" % style.get("primary_style","未指定")
    prompt += "色调: %s\n" % style.get("color_tone","未指定")
    prompt += "设计关键词: %s\n" % style.get("keywords","")
    if space.get("rooms"):
        prompt += "空间: %s\n" % ", ".join(r["name"] for r in space["rooms"])
    if special.get("eco_standard"):
        prompt += "环保要求: %s\n" % special["eco_standard"]

    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":prompt},
        ],
        temperature=0.6,
        max_tokens=2000,
    )

    content = resp.choices[0].message.content
    # 解析 JSON
    import re
    try:
        data = json.loads(content)
    except:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
        else:
            data = {"scheme_name":"解析错误","base_color":{"hex":"#CCC"}}

    # 输出目录
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    os.makedirs(out_dir, exist_ok=True)

    # 渲染色卡
    img_path = render_palette_card(data, out_dir)
    data["palette_image"] = img_path
    return data


def render_palette_card(data, output_dir):
    width, height = 1200, 600
    img = Image.new("RGB", (width, height), "#F5F5F5")
    draw = ImageDraw.Draw(img)

    try:
        font_l = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 36)
        font_m = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 24)
        font_s = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
    except:
        font_l = font_m = font_s = ImageFont.load_default()

    draw.text((40, 30), data.get("scheme_name","色彩方案"), fill="#333", font=font_l)
    if data.get("description"):
        draw.text((40, 78), data["description"], fill="#888", font=font_m)

    colors = [
        ("主色 60%%", data.get("base_color",{})),
        ("辅色 30%%", data.get("secondary_color",{})),
        ("点缀色 10%%", data.get("accent_color",{})),
    ]

    y0 = 140; bw = 320; bh = 120; gap = 30; x0 = 60

    for i, (label, cd) in enumerate(colors):
        x = x0 + i*(bw+gap)
        try:
            rgb = hex_to_rgb(cd.get("hex","#CCCCCC"))
        except:
            rgb = (200,200,200)
        draw.rectangle([x, y0, x+bw, y0+bh], fill=rgb, outline="#DDD")
        draw.text((x, y0-30), label, fill="#666", font=font_m)
        draw.text((x, y0+bh+8), cd.get("name",""), fill="#333", font=font_m)
        draw.text((x, y0+bh+36), cd.get("hex",""), fill="#999", font=font_s)
        usage = cd.get("usage","")
        if usage:
            draw.text((x, y0+bh+58), usage[:22], fill="#888", font=font_s)

    rooms = data.get("room_suggestions",[])
    if rooms:
        yr = y0+bh+110
        draw.text((40, yr), "空间配色建议", fill="#333", font=font_m)
        for j, rm in enumerate(rooms[:4]):
            ry = yr + 40 + j*50
            try:
                cr = hex_to_rgb(rm.get("base","#CCC"))
                ca = hex_to_rgb(rm.get("accent","#EEE"))
            except:
                cr, ca = (200,200,200), (220,220,220)
            draw.ellipse([60, ry+5, 80, ry+25], fill=cr)
            draw.ellipse([90, ry+5, 110, ry+25], fill=ca)
            draw.text((120, ry+2), "%s  %s"%(rm.get("room",""),rm.get("note","")[:30]),
                     fill="#444", font=font_s)

    path = os.path.join(output_dir, "色彩方案.png")
    img.save(path)
    return path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    r = generate_color_palette(inp)
    print("方案:", r.get("scheme_name"))
    print("主色:", r.get("base_color",{}).get("name"), r.get("base_color",{}).get("hex"))
    print("辅色:", r.get("secondary_color",{}).get("name"), r.get("secondary_color",{}).get("hex"))
    print("点缀色:", r.get("accent_color",{}).get("name"), r.get("accent_color",{}).get("hex"))
    print("色卡:", r.get("palette_image"))
