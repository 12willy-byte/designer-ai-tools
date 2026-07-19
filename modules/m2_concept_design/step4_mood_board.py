"""Step 4: 风格意向板合成器
用 Pillow 把设计关键词、色彩方案、材质方案合成一张专业的 Mood Board
"""
import json, os, sys, math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.design_schema import normalize_conditions

# 载入之前步骤的成果
def load_step_output(conditions_path, step_name):
    base_dir = os.path.dirname(os.path.abspath(conditions_path))
    out_dir = os.path.join(base_dir, "concept_output")
    paths = {
        "color_palette": os.path.join(out_dir, "色彩方案.png"),
        "material_board": os.path.join(out_dir, "材质方案.png"),
    }
    return paths.get(step_name)


def generate_mood_board(conditions_json_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = normalize_conditions(json.load(f))

    style = conditions.get("style", {})
    space = conditions.get("space_data", {})
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    os.makedirs(out_dir, exist_ok=True)

    # 画板大小
    W, H = 1920, 1200
    img = Image.new("RGB", (W, H), "#F5F3F0")
    draw = ImageDraw.Draw(img)

    from core.font_utils import load_cjk_font
    font_title = load_cjk_font(52)
    font_sub = load_cjk_font(32)
    font_body = load_cjk_font(22)
    font_small = load_cjk_font(18)

    # ── 上半：标题区 ──
    draw.rectangle([0, 0, W, 90], fill="#1A1A2E")
    draw.text((40, 18), "MOOD BOARD  ·  风格意向板", fill="#FFFFFF", font=font_sub)

    project_name = conditions.get("project",{}).get("name","")
    if project_name:
        draw.text((40, 55), project_name, fill="#AAAAAA", font=font_small)

    # ── 左侧：设计关键词 + 调性 ──
    keywords_text = style.get("keywords","")
    keywords = [k.strip() for k in keywords_text.replace("、"," ").replace("/"," ").split() if k.strip()]
    if not keywords:
        keywords = ["现代", "简约", "自然", "通透", "温馨"]

    x_left = 40
    y0 = 130

    draw.text((x_left, y0), "设计关键词", fill="#1A1A2E", font=font_sub)
    ky = y0 + 55
    for kw in keywords[:5]:
        # 关键词小标签
        kw = kw.strip("，。、")
        if not kw: continue
        tw = draw.textlength(kw, font=font_body)
        draw.rectangle([x_left, ky, x_left+tw+30, ky+40], fill="#1A1A2E", outline=None)
        draw.text((x_left+15, ky+6), kw, fill="#FFFFFF", font=font_body)
        ky += 50

    # 设计调性
    ky += 20
    draw.text((x_left, ky), "设计调性", fill="#1A1A2E", font=font_sub)
    ky += 45
    tones = [
        ("理性", "功能分区合理"),
        ("感性", "光影氛围温暖"),
        ("简约", "线条干净利落"),
    ]
    for t_label, t_desc in tones:
        draw.rectangle([x_left, ky, x_left+150, ky+35], fill="#E8E0D8", outline=None)
        draw.text((x_left+12, ky+5), "%s / %s" % (t_label, t_desc), fill="#555", font=font_small)
        ky += 42

    # ── 中央：主视觉区域 ──
    # 加载色彩方案和材质方案的小图
    cx = 400
    cy = 130
    area_w = 1080
    area_h = 800

    # 画一个大的装饰色块（代表整体氛围）
    base_color_hex = "#F5EDE4"
    colors_info = [
        ("主色", "#F5F0EB", "暖灰白"),
        ("辅色", "#7A9C9E", "雾霾蓝"),
        ("点缀", "#D4836D", "陶土橙"),
    ]
    wood_label = "浅橡木"
    try:
        pal_data = json.load(open(os.path.join(out_dir, "色彩方案色板.json"), "r", encoding="utf-8"))
        base_color_hex = pal_data.get("base_color", {}).get("hex", base_color_hex)
        # 右侧色板使用真实色彩方案，避免意向板与色板步骤互相矛盾
        swatches = []
        for label, key in (("主色", "base_color"), ("辅色", "secondary_color"), ("点缀", "accent_color")):
            c = pal_data.get(key) or {}
            if c.get("hex"):
                swatches.append((label, c["hex"], c.get("name", "")))
        if swatches:
            colors_info = swatches
        if pal_data.get("wood_tone"):
            wood_label = str(pal_data["wood_tone"]).split("或")[0].split("，")[0].strip() or wood_label
    except Exception:
        pass

    # 底部标签来自输入的风格与关键词，不使用与项目无关的固定文案
    mood_tags = []
    if style.get("primary_style"):
        mood_tags.append(style["primary_style"])
    mood_tags += [k for k in keywords if k not in mood_tags][:4]
    if not mood_tags:
        mood_tags = ["现代简约", "中性色系", "通透", "温润"]

    # 抽象氛围背景
    for i in range(5):
        ly = cy + 30 + i * 30
        alpha = 20 + i * 15
        c_val = 240 - i * 8
        draw.rectangle([cx, ly, cx+area_w, ly+28],
                       fill=(c_val, c_val-3, c_val-8))

    # 设计定位文本
    brief_path = os.path.join(out_dir, "设计定位.txt")
    brief_full = ""
    if os.path.exists(brief_path):
        brief_full = open(brief_path, "r", encoding="utf-8").read()
    else:
        brief_full = "以中性色为基调的现代简约住宅，通过木饰面与微水泥的材质碰撞，营造温润有序的居住空间。"
    # 意向板图片空间有限，仅绘制开头片段；完整文本保留在 设计定位.txt 中。
    brief_text = brief_full[:200]

    draw.text((cx+20, cy+20), "设计定位", fill="#1A1A2E", font=font_sub)
    # 手动换行，避免长文本单行溢出或行与行重叠；换行符会让 Pillow 在同一起点叠打
    flat_text = " ".join(brief_text.split())
    wrap_width = 38
    wrapped = [flat_text[i:i + wrap_width] for i in range(0, min(len(flat_text), 190), wrap_width)]
    for li, line in enumerate(wrapped[:5]):
        draw.text((cx+20, cy+60 + li * 42), line, fill="#666666", font=font_body)

    # 空间数据展示
    sy = cy + 280
    draw.text((cx+20, sy), "空间概况", fill="#1A1A2E", font=font_sub)
    if space.get("rooms"):
        sy += 45
        for rm in space["rooms"][:4]:
            area_str = "%.1f m2" % rm["area_m2"]
            draw.text((cx+20, sy), "  %s  %s" % (rm["name"], area_str), fill="#555", font=font_body)
            draw.rectangle([cx+20, sy+28, cx+20+int(rm["area_m2"]/30*150), sy+30],
                          fill="#C4A484", outline=None)
            sy += 45

    # ── 右侧：色板预览 ──
    rx = cx + area_w + 30
    ry = 130

    draw.text((rx, ry), "色板", fill="#1A1A2E", font=font_sub)
    ry += 45

    for c_label, c_hex, c_name in colors_info:
        try:
            c_rgb = tuple(int(c_hex.lstrip("#")[i:i+2], 16) for i in (0,2,4))
        except:
            c_rgb = (200,200,200)
        draw.rectangle([rx, ry, rx+60, ry+60], fill=c_rgb, outline="#DDD")
        draw.text((rx+70, ry+5), c_name, fill="#333", font=font_body)
        draw.text((rx+70, ry+35), c_hex, fill="#999", font=font_small)
        ry += 75

    # 木色
    draw.text((rx, ry+5), "木色: %s" % wood_label, fill="#555", font=font_body)
    draw.rectangle([rx, ry+32, rx+80, ry+45], fill="#D4A76A", outline="#DDD")

    # ── 底部：全局标签 ──
    bar_y = H - 60
    draw.rectangle([0, bar_y, W, H], fill="#1A1A2E")
    tags = mood_tags
    tx = 40
    for tag in tags:
        tw = draw.textlength(tag, font=font_small)
        draw.rectangle([tx, bar_y+12, tx+tw+24, bar_y+48], fill="#2A2A4E", outline=None)
        draw.text((tx+12, bar_y+16), tag, fill="#CCCCCC", font=font_small)
        tx += tw + 34

    # 保存
    path = os.path.join(out_dir, "风格意向板.png")
    img.save(path)

    # 同时保存设计定位文本供后面步骤使用（完整文本，不截断）
    with open(os.path.join(out_dir, "设计定位.txt"), "w", encoding="utf-8") as f:
        f.write(brief_full)

    return path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    p = generate_mood_board(inp)
    print("Mood Board:", p)
