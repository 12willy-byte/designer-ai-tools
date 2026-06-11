"""Fix: 给 PPT 生成器加 PDF 导出"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

# 追加 PDF 导出功能到 step7_build_pptx.py
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from PIL import Image

def export_pptx_to_pdf(pptx_path, pdf_path):
    """PPTX 无法直接转 PDF（无 Office），生成一个替代 PDF 摘要"""
    from pptx import Presentation
    prs = Presentation(pptx_path)
    c = canvas.Canvas(pdf_path, pagesize=landscape(A4))
    w, h = landscape(A4)

    for i, slide in enumerate(prs.slides):
        c.setFillColorRGB(0.1, 0.1, 0.18)
        c.rect(0, 0, w, h, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(50, h - 80, "概念方案 - 第%d页" % (i + 1))

        y = h - 120
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        c.setFont("Helvetica", 12)
                        c.setFillColorRGB(0.8, 0.8, 0.8)
                        c.drawString(50, y, text[:80])
                        y -= 18

            if shape.shape_type == 13:  # Picture
                try:
                    img = Image.open(shape.image.blob)
                    img_path = "/tmp/slide_img.png"
                    img.save(img_path)
                    c.drawImage(img_path, 50, y - 200, width=400, height=200)
                    y -= 220
                except:
                    pass

        c.showPage()
    c.save()
    return pdf_path


if __name__ == "__main__":
    pptx = sys.argv[1] if len(sys.argv) > 1 else "templates/concept_output/概念方案.pptx"
    pdf = sys.argv[2] if len(sys.argv) > 2 else pptx.replace(".pptx", ".pdf")
    r = export_pptx_to_pdf(pptx, pdf)
    print("PDF:", r, os.path.getsize(r), "bytes")
