'''
导出到 PDF - 方案书、验收单
使用 reportlab 生成，无需 Office
'''
import os, json
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, PageBreak)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 注册中文字体
_FONT_REGISTERED = False

def _register_font():
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    font_paths = [
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simsun.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont('CJK', path))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue
    # Fallback: use built-in Helvetica
    _FONT_REGISTERED = True


def _font_name():
    _register_font()
    return 'CJK'


def export_design_brief_pdf(conditions: dict, ai_brief: str, output_path: str):
    '''导出设计定位方案书 PDF'''
    _register_font()
    fn = _font_name()
    
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                           leftMargin=2*cm, rightMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CNTitle', parent=styles['Title'],
                                 fontName=fn, fontSize=20, spaceAfter=20,
                                 textColor=HexColor('#1F4E79'))
    heading_style = ParagraphStyle('CNHeading', parent=styles['Heading2'],
                                   fontName=fn, fontSize=14, spaceAfter=10,
                                   textColor=HexColor('#1F4E79'))
    body_style = ParagraphStyle('CNBody', parent=styles['Normal'],
                                fontName=fn, fontSize=10, leading=18,
                                spaceAfter=8)
    
    story = []
    project = conditions.get('project', {})
    
    story.append(Paragraph(f"设计定位方案书", title_style))
    story.append(Paragraph(f"项目：{project.get('name', '未命名')}", heading_style))
    story.append(Spacer(1, 10))
    
    # 设计定位
    story.append(Paragraph('设计定位说明', heading_style))
    for para in ai_brief.split('\n'):
        para = para.strip()
        if para:
            story.append(Paragraph(para, body_style))
    
    story.append(Spacer(1, 20))
    
    # 项目概况
    story.append(Paragraph('项目概况', heading_style))
    info_data = [
        ['项目名称', project.get('name', '-')],
        ['房屋类型', project.get('house_type', '-')],
        ['设计类型', project.get('design_type', '-')],
    ]
    t = Table(info_data, colWidths=[4*cm, 10*cm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), fn),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#D6E4F0')),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#CCCCCC')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    
    doc.build(story)
    return output_path


def export_checklist_pdf(checklist: list[dict], output_path: str,
                         project_name: str = ''):
    '''导出验收清单 PDF'''
    _register_font()
    fn = _font_name()
    
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                           leftMargin=2*cm, rightMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CNTitle', parent=styles['Title'],
                                 fontName=fn, fontSize=20, spaceAfter=20,
                                 textColor=HexColor('#1F4E79'))
    heading_style = ParagraphStyle('CNHeading', parent=styles['Heading2'],
                                   fontName=fn, fontSize=14, spaceAfter=10,
                                   textColor=HexColor('#1F4E79'))
    item_style = ParagraphStyle('CNItem', parent=styles['Normal'],
                                fontName=fn, fontSize=11, leading=22,
                                leftIndent=20)
    
    story = []
    story.append(Paragraph(f'竣工验收清单 - {project_name}', title_style))
    story.append(Spacer(1, 10))
    
    for cat in checklist:
        story.append(Paragraph(cat['category'], heading_style))
        for item in cat['items']:
            story.append(Paragraph(f'□  {item}', item_style))
        story.append(Spacer(1, 10))
    
    story.append(Spacer(1, 30))
    story.append(Paragraph('业主签字：______________    日期：______________',
                          item_style))
    
    doc.build(story)
    return output_path
