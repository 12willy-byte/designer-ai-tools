"""生成测试用矢量 PDF 毛坯图纸（两室一厅，1:50，A3 横向）。

样本仅供离线验收与演示：外墙/内隔墙线、门洞缺口+门扇斜线、窗洞+窗符号、
尺寸标注数字、房间名文字、图签（含比例文字）。平面坐标设计值见下方常量
（单位 mm）。同时提供 build_raster_sample 生成图片型 PDF 用于拒绝路径验证。

用法: python3 scripts/generate_sample_pdf_plan.py [输出路径]
默认写入 templates/sample_floor_plan_vector.pdf
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


SCALE_DENOM = 50                      # 1:50
MM_TO_PT = 72.0 / 25.4 / SCALE_DENOM  # ≈0.0567 pt/mm
PT_TO_MM = 1.0 / MM_TO_PT             # ≈17.64 mm/pt
ORIGIN_PT = (90.0, 110.0)             # 平面 (0,0) 在页面上的偏移

# 墙线（mm）。门洞/窗洞以缺口表示；线段在 T 型交叉处已预先断开。
WALLS_MM = [
    # 底墙（窗洞 5600-7000）
    (0, 0, 4800, 0), (4800, 0, 5600, 0), (7000, 0, 8400, 0),
    # 右墙（在内墙 B 处断开）
    (8400, 0, 8400, 4000), (8400, 4000, 8400, 6400),
    # 顶墙（在内墙 A 处断开）
    (8400, 6400, 4800, 6400), (4800, 6400, 0, 6400),
    # 左墙
    (0, 6400, 0, 0),
    # 内墙 A（x=4800，门洞 1200-2000）
    (4800, 0, 4800, 1200), (4800, 2000, 4800, 6400),
    # 内墙 B（y=4000，门洞 6200-7000）
    (4800, 4000, 6200, 4000), (7000, 4000, 8400, 4000),
]
# 门扇斜线（45°，长 800mm）
DOOR_LEAVES_MM = [
    (4800, 1200, 4800 + 565.7, 1200 + 565.7),
    (6200, 4000, 6200 + 565.7, 4000 + 565.7),
]
# 窗符号（底墙窗洞内侧两条平行线）
WINDOW_SYMBOLS_MM = [
    (5600, 150, 7000, 150),
    (5600, 300, 7000, 300),
]
# 尺寸标注数字（紧贴对应线段，文字中心 -> 线段）
DIM_TEXTS_MM = [
    ("4800", 2400, 6760),   # 顶墙左段
    ("3600", 6600, 6760),   # 顶墙右段
    ("6400", -450, 3200),   # 左墙
    ("2400", 8850, 5200),   # 右墙上段
    ("4000", 8850, 2000),   # 右墙下段
]
ROOM_TEXTS_MM = [
    ("客厅", 2400, 3200),
    ("主卧", 6600, 5200),
    ("次卧", 6600, 1800),
]
TITLE_TEXT = "两室一厅毛坯平面图"
SCALE_TEXT = "比例 1:50"

GROUND_TRUTH = {
    "scale_denom": SCALE_DENOM,
    "pt_to_mm": PT_TO_MM,
    "rooms": {"客厅": 30.72, "次卧": 14.4, "主卧": 8.64},
    "door_count": 2,
    "window_count": 1,
    "outer_area_m2": 53.76,
}


def _pt(x_mm, y_mm):
    return (ORIGIN_PT[0] + x_mm * MM_TO_PT, ORIGIN_PT[1] + y_mm * MM_TO_PT)


def _register_cjk():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def build_vector_sample(path, with_dimensions=True, with_scale_text=True):
    """生成矢量 PDF 样本。可关闭尺寸标注/比例文字以测试未校准路径。"""
    font = _register_cjk()
    c = canvas.Canvas(path, pagesize=landscape(A3))
    c.setLineWidth(0.8)

    for x1, y1, x2, y2 in WALLS_MM + DOOR_LEAVES_MM + WINDOW_SYMBOLS_MM:
        c.line(*_pt(x1, y1), *_pt(x2, y2))

    c.setFont(font, 10)
    if with_dimensions:
        for text, x, y in DIM_TEXTS_MM:
            c.drawCentredString(*_pt(x, y), text)

    c.setFont(font, 14)
    for text, x, y in ROOM_TEXTS_MM:
        c.drawCentredString(*_pt(x, y), text)

    # 图签
    c.setFont(font, 12)
    c.drawString(ORIGIN_PT[0], 70, TITLE_TEXT)
    if with_scale_text:
        c.setFont(font, 10)
        c.drawString(ORIGIN_PT[0] + 250, 70, SCALE_TEXT)
    c.setFont(font, 8)
    c.drawString(ORIGIN_PT[0], 50, "图签：示例图纸，仅供自动化测试")

    c.showPage()
    c.save()
    return path


def build_raster_sample(path):
    """生成图片型（扫描风格）PDF：页面只有一张位图，没有矢量路径。"""
    from PIL import Image, ImageDraw

    png_path = os.path.splitext(path)[0] + "_page.png"
    img = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 750, 550], outline="black", width=3)
    draw.line([400, 50, 400, 550], fill="black", width=2)
    img.save(png_path)

    c = canvas.Canvas(path, pagesize=landscape(A3))
    c.drawImage(png_path, 100, 100, width=600, height=450)
    c.showPage()
    c.save()
    os.remove(png_path)
    return path


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "templates", "sample_floor_plan_vector.pdf")
    build_vector_sample(output)
    print(f"已生成矢量 PDF 样本: {output}")
