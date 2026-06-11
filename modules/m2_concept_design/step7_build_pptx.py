"""Step 7: 概念方案 PPT 打包器
把前面所有产出合成一份可演示的 PPT
"""
import json, os, sys, math
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def build_pptx(conditions_json_path, output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    os.makedirs(out_dir, exist_ok=True)

    project = conditions.get("project", {})
    style = conditions.get("style", {})
    space = conditions.get("space_data", {})
    brief_path = os.path.join(out_dir, "设计定位.txt")

    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    W = prs.slide_width
    H = prs.slide_height

    COLORS = {
        "dark": RGBColor(0x1A, 0x1A, 0x2E),
        "accent": RGBColor(0xC4, 0xA4, 0x84),
        "gray": RGBColor(0x66, 0x66, 0x66),
        "light": RGBColor(0xF5, 0xF3, 0xF0),
        "white": RGBColor(0xFF, 0xFF, 0xFF),
    }

    def add_bg(slide, color=COLORS["light"]):
        bg = slide.background
        fill = bg.fill
        fill.solid()
        fill.fore_color.rgb = color

    def add_textbox(slide, left, top, width, height, text, font_size=18,
                    color=COLORS["dark"], bold=False, align=PP_ALIGN.LEFT):
        txBox = slide.shapes.add_textbox(left, top, width, height)
        tf = txBox.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(font_size)
        p.font.color.rgb = color
        p.font.bold = bold
        p.alignment = align
        return txBox

    def add_img(slide, img_path, left, top, width, height=None):
        if not os.path.exists(img_path):
            return None
        if height is None:
            height = width * 0.75
        return slide.shapes.add_picture(img_path, left, top, width, height)

    def add_rect(slide, left, top, width, height, color):
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
        shape.fill.solid()
        shape.fill.fore_color.rgb = color
        shape.line.fill.background()
        return shape

    # ── Slide 1: 封面 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    add_bg(slide, COLORS["dark"])

    # 装饰条
    add_rect(slide, 0, Inches(3.2), W, Pt(4), COLORS["accent"])

    project_name = project.get("name", "设计项目")
    add_textbox(slide, Inches(1), Inches(1.5), Inches(10), Inches(1.5),
               project_name, font_size=48, color=COLORS["white"], bold=True)

    style_name = style.get("primary_style", "现代简约")
    add_textbox(slide, Inches(1), Inches(3.6), Inches(10), Inches(0.8),
               "%s  ·  概念方案" % style_name, font_size=28, color=COLORS["accent"])

    area_str = ""
    if space.get("total_area_m2"):
        area_str += "%.0f m²" % space["total_area_m2"]
    if space.get("total_rooms"):
        area_str += "  ·  %d室" % space["total_rooms"]
    add_textbox(slide, Inches(1), Inches(4.6), Inches(10), Inches(0.6),
               area_str, font_size=18, color=RGBColor(0x88, 0x88, 0x88))

    add_textbox(slide, Inches(1), Inches(6.5), Inches(10), Inches(0.5),
               "AI 辅助概念设计方案", font_size=14, color=RGBColor(0x66, 0x66, 0x66))

    # ── Slide 2: 设计定位 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)

    add_rect(slide, 0, 0, Pt(8), H, COLORS["accent"])
    add_textbox(slide, Inches(0.6), Inches(0.5), Inches(1), Inches(1),
               "01", font_size=48, color=COLORS["accent"], bold=True)
    add_textbox(slide, Inches(0.6), Inches(1.3), Inches(2), Inches(0.5),
               "设计定位", font_size=24, color=COLORS["dark"], bold=True)

    brief_text = ""
    if os.path.exists(brief_path):
        brief_text = open(brief_path, "r", encoding="utf-8").read()
    if not brief_text:
        brief_text = "以中性色为基调的现代简约住宅，通过木饰面与微水泥的材质碰撞，营造温润有序的居住空间。"

    add_textbox(slide, Inches(2.5), Inches(2), Inches(9), Inches(4),
               brief_text, font_size=22, color=COLORS["gray"])

    # 关键词标签
    keywords = style.get("keywords", "现代,简约,自然")
    kws = [k.strip() for k in keywords.replace("、", " ").split() if k.strip()]
    if kws:
        x_pos = Inches(2.5)
        for kw in kws[:5]:
            add_rect(slide, x_pos, Inches(5.5), Inches(1.5), Inches(0.45), COLORS["accent"])
            add_textbox(slide, x_pos, Inches(5.5), Inches(1.5), Inches(0.45),
                       kw, font_size=16, color=COLORS["white"], align=PP_ALIGN.CENTER)
            x_pos += Inches(1.7)

    # ── Slide 3: 空间概况 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)

    add_textbox(slide, Inches(0.8), Inches(0.4), Inches(2), Inches(0.6),
               "02  空间概况", font_size=28, color=COLORS["dark"], bold=True)

    if space.get("rooms"):
        y = Inches(1.5)
        for rm in space["rooms"]:
            # 房间名
            add_rect(slide, Inches(0.8), y, Inches(2.5), Inches(0.6), COLORS["accent"])
            add_textbox(slide, Inches(0.8), y, Inches(2.5), Inches(0.6),
                       rm["name"], font_size=18, color=COLORS["white"], align=PP_ALIGN.CENTER)
            # 尺寸
            add_textbox(slide, Inches(3.6), y, Inches(3), Inches(0.6),
                       "%d×%d mm" % (rm["width_mm"], rm["height_mm"]),
                       font_size=16, color=COLORS["dark"])
            # 面积
            add_textbox(slide, Inches(6.5), y, Inches(2), Inches(0.6),
                       "%.1f m²" % rm["area_m2"], font_size=16, color=COLORS["gray"])
            y += Inches(0.8)

    # ── Slide 4: 色彩方案 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)

    add_textbox(slide, Inches(0.8), Inches(0.4), Inches(4), Inches(0.6),
               "03  色彩方案", font_size=28, color=COLORS["dark"], bold=True)

    palette_img = os.path.join(out_dir, "色彩方案.png")
    if os.path.exists(palette_img):
        add_img(slide, palette_img, Inches(0.8), Inches(1.3), Inches(11))

    # ── Slide 5: 材质方案 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)

    add_textbox(slide, Inches(0.8), Inches(0.4), Inches(4), Inches(0.6),
               "04  材质方案", font_size=28, color=COLORS["dark"], bold=True)

    mat_img = os.path.join(out_dir, "材质方案.png")
    if os.path.exists(mat_img):
        add_img(slide, mat_img, Inches(0.8), Inches(1.3), Inches(11))

    # ── Slide 6: 风格意向板 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)

    add_textbox(slide, Inches(0.8), Inches(0.4), Inches(4), Inches(0.6),
               "05  风格意向板", font_size=28, color=COLORS["dark"], bold=True)

    mood_img = os.path.join(out_dir, "风格意向板.png")
    if os.path.exists(mood_img):
        add_img(slide, mood_img, Inches(0.8), Inches(1.2), Inches(11.5))

    # ── Slide 7: 布局方案 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)

    add_textbox(slide, Inches(0.8), Inches(0.4), Inches(4), Inches(0.6),
               "06  布局方案", font_size=28, color=COLORS["dark"], bold=True)

    # 布局方案的文字摘要
    layout_path = os.path.join(out_dir, "布局方案.dxf")
    if os.path.exists(layout_path):
        # 读取 DXf 中的文字建议作为布局说明
        import ezdxf
        doc = ezdxf.readfile(layout_path)
        texts = []
        for e in doc.modelspace():
            if e.dxftype() == "TEXT" and e.dxf.layer.startswith("AI方案"):
                texts.append(e.dxf.text)

        if texts:
            y = Inches(1.5)
            for t in texts[:15]:
                add_textbox(slide, Inches(1), y, Inches(11), Inches(0.4),
                           t, font_size=14, color=COLORS["gray"])
                y += Inches(0.38)
                if y > Inches(6.5):
                    break

    # ── Slide 8~: 氛围图 ──
    # 找到所有氛围图
    atmos_files = sorted([f for f in os.listdir(out_dir) if "氛围图" in f and f.endswith(".png")])

    for i, atmos_file in enumerate(atmos_files):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        add_bg(slide, COLORS["dark"])

        room_name = atmos_file.replace("氛围图.png", "")
        add_textbox(slide, Inches(0.8), Inches(0.3), Inches(6), Inches(0.6),
                   "0%s  %s 氛围图" % (str(i + 7), room_name),
                   font_size=24, color=COLORS["accent"], bold=True)

        atmos_path = os.path.join(out_dir, atmos_file)
        if os.path.exists(atmos_path):
            # 图片居中
            img_w = Inches(9.5)
            img_h = Inches(5.5)
            left = (W - img_w) // 2
            top = Inches(1.3)
            add_img(slide, atmos_path, left, top, img_w, img_h)

    # ── 最后一页: 结尾 ──
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, COLORS["dark"])

    add_rect(slide, Inches(4.5), Inches(3.5), Inches(4), Pt(3), COLORS["accent"])
    add_textbox(slide, Inches(1), Inches(2.5), Inches(11), Inches(1),
               "谢谢观看", font_size=44, color=COLORS["white"], bold=True,
               align=PP_ALIGN.CENTER)
    add_textbox(slide, Inches(1), Inches(4), Inches(11), Inches(0.6),
               "期待与您共同实现这个理想家", font_size=20, color=COLORS["accent"],
               align=PP_ALIGN.CENTER)

    # 保存
    prs.save(output_path)
    return output_path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "../templates/concept_output/概念方案.pptx"
    r = build_pptx(inp, out)
    sz = os.path.getsize(out)
    print("OK: %s (%d bytes, %d slides)" % (r, sz,
          len(Presentation(out).slides)))
