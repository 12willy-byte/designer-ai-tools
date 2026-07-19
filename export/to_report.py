# -*- coding: utf-8 -*-
"""
pdf_report - Professional multi-page PDF report generator
Integrates ALL analysis results into a single deliverable PDF.
Uses reportlab for clean typography and layout.
"""
import json, os, math, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.scene_utils import normalize as _n
def generate_comprehensive_report(scene, output_path="output/comprehensive_report.pdf", 
                                   critique=None, cost=None, validation=None,
                                   electrical=None, mep=None, daylight=None,
                                   acoustic=None, fire_r=None, accessibility=None,
                                   fengshui=None, energy=None, schedule=None,
                                   materials=None, layout_count=0) -> str:
    """Generate a comprehensive multi-section PDF report."""
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm, cm
        from reportlab.lib.colors import HexColor, black, grey, white
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                         TableStyle, PageBreak, HRFlowable, Image)
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        # Fallback: generate HTML report
        return _generate_html_report(scene, output_path.replace('.pdf', '.html'),
                                      critique, cost, validation, electrical, mep,
                                      daylight, acoustic, fire_r, accessibility,
                                      fengshui, energy, schedule, materials, layout_count)
    
    # Register Chinese font
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    font_registered = False
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont('CJK', fp))
                font_registered = True
                break
            except: pass
    
    if not font_registered:
        return _generate_html_report(scene, output_path.replace('.pdf', '.html'),
                                      critique, cost, validation, electrical, mep,
                                      daylight, acoustic, fire_r, accessibility,
                                      fengshui, energy, schedule, materials, layout_count)
    
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                           leftMargin=20*mm, rightMargin=20*mm,
                           topMargin=15*mm, bottomMargin=15*mm)
    
    styles = getSampleStyleSheet()
    cn = lambda s: ParagraphStyle(s, fontName='CJK', fontSize=10, leading=14)
    title_style = ParagraphStyle('CNTitle', fontName='CJK', fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=10)
    h2_style = ParagraphStyle('CNH2', fontName='CJK', fontSize=14, leading=18, spaceBefore=12, spaceAfter=6)
    h3_style = ParagraphStyle('CNH3', fontName='CJK', fontSize=12, leading=16, spaceBefore=8, spaceAfter=4)
    body_style = ParagraphStyle('CNBody', fontName='CJK', fontSize=9, leading=13)
    
    story = []
    rooms = [_n(r) for r in (get_rooms(scene))]
    total_area = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms)
    n_rooms = len(rooms)
    
    # ---- Cover ----
    story.append(Spacer(1, 40*mm))
    story.append(Paragraph(f"室内设计全案报告", title_style))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(f"项目面积: {total_area:.1f} m² | {n_rooms} 间", ParagraphStyle('sub', fontName='CJK', fontSize=11, alignment=TA_CENTER)))
    story.append(Paragraph(f"生成日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle('date', fontName='CJK', fontSize=9, alignment=TA_CENTER, textColor=grey)))
    story.append(PageBreak())
    
    # ---- 1. Project Overview ----
    story.append(Paragraph("一、项目概况", h2_style))
    story.append(Paragraph(f"总面积: {total_area:.1f} m² | 房间数: {n_rooms} | 墙体: {len(getattr(scene,'walls',[]) or [])}", body_style))
    room_data = [[r.get('name','?'), f"{r.get('length_mm',0)/1000:.1f}x{r.get('width_mm',0)/1000:.1f}m", f"{r.get('length_mm',0)*r.get('width_mm',0)/1e6:.1f}m²", r.get('type','?')] for r in rooms]
    if room_data:
        t = Table([['房间','尺寸','面积','类型']] + room_data)
        t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'CJK'),('FONTSIZE',(0,0),(-1,-1),8),
                               ('GRID',(0,0),(-1,-1),0.5,grey),('BACKGROUND',(0,0),(-1,0),HexColor('#333')),
                               ('TEXTCOLOR',(0,0),(-1,0),white)]))
        story.append(t)
    story.append(Spacer(1, 5*mm))
    
    # ---- 2. Validation ----
    if validation:
        story.append(Paragraph("二、质量校验", h2_style))
        story.append(Paragraph(f"评分: {validation.score:.0f}/100 | {'通过' if validation.passed else '未通过'} | 错误: {len(validation.errors)} | 警告: {len(validation.warnings)}", body_style))
    
    # ---- 3. Design Critique ----
    if critique:
        story.append(Paragraph("三、设计评审", h2_style))
        story.append(Paragraph(f"评分: {critique.score:.0f}/100 — {critique.summary}", body_style))
        for item in critique.items[:8]:
            story.append(Paragraph(f"· [{item.cat}] {item.title}: {item.detail}", body_style))
    
    # ---- 4. Cost ----
    if cost:
        story.append(Paragraph("四、造价估算", h2_style))
        s = cost.get('summary', {})
        story.append(Paragraph(f"总价: ¥{s.get('grand_total',0):,.0f} ({s.get('per_sqm',0):,.0f}/m²)", body_style))
        story.append(Paragraph(f"硬装: ¥{s.get('hard_decoration',0):,.0f} | 软装: ¥{s.get('soft_decoration',0):,.0f} | 设计费: ¥{s.get('design_fee',0):,.0f}", body_style))
    
    # ---- 5. Electrical ----
    if electrical:
        story.append(Paragraph("五、电气规划", h2_style))
        story.append(Paragraph(f"点位: {len(electrical.points)} | 负荷: {electrical.total_load_w}W | 总开: {electrical.main_breaker_a}A", body_style))
    
    # ---- 6. MEP ----
    if mep:
        story.append(Paragraph("六、给排水+暖通", h2_style))
        story.append(Paragraph(f"给排水点位: {len(mep.plumbing)} | 暖通分区: {len(mep.hvac)} | 总冷量: {mep.total_ac_capacity_kw}kW", body_style))
    
    # ---- 7. Daylight ----
    if daylight:
        story.append(Paragraph("七、采光分析", h2_style))
        for d in daylight[:6]:
            story.append(Paragraph(f"· {d.room_name}: {d.natural_light_score}/100 ({d.orientation}) {'达标' if d.meets_standard else '不达标'}", body_style))
    
    # ---- 8. Energy ----
    if energy:
        story.append(Paragraph("八、能效分析", h2_style))
        story.append(Paragraph(f"墙体U值: {energy.wall_u_value} | 供暖负荷: {energy.heating_load_kw}kW | 制冷: {energy.cooling_load_kw}kW", body_style))
    
    # ---- 9. Acoustic ----
    if acoustic:
        story.append(Paragraph("九、声学分析", h2_style))
        story.append(Paragraph(f"总体: {'达标' if acoustic.overall_pass else '需改善'}", body_style))
    
    # ---- 10. Fire Safety ----
    if fire_r:
        story.append(Paragraph("十、消防安全", h2_style))
        story.append(Paragraph(f"通过: {fire_r.pass_count}/{len(fire_r.checks)} | 设备: {len(fire_r.equipment_needed)}项", body_style))
    
    # ---- 11. Accessibility ----
    if accessibility:
        story.append(Paragraph("十一、无障碍", h2_style))
        story.append(Paragraph(f"评分: {accessibility.score}/100", body_style))
    
    # ---- 12. Feng Shui ----
    if fengshui:
        story.append(Paragraph("十二、风水分析", h2_style))
        story.append(Paragraph(f"吉: {fengshui.good_count} | 煞: {fengshui.bad_count} | {fengshui.overall}", body_style))
    
    # ---- 13. Schedule ----
    if schedule:
        story.append(Paragraph("十三、施工计划", h2_style))
        story.append(Paragraph(f"总工期: {schedule.total_days}天 | 关键路径: {len(schedule.critical_path)}工序 | 总成本: ¥{schedule.total_cost:,}", body_style))
    
    # ---- 14. Materials ----
    if materials:
        story.append(Paragraph("十四、材料清单", h2_style))
        mat_total = sum(o.total_cost for o in materials if not o.name.startswith('==='))
        story.append(Paragraph(f"{len(materials)-1}类材料 | 合计: ¥{mat_total:,.0f}", body_style))
    
    story.append(Spacer(1, 10*mm))
    story.append(HRFlowable(width="100%", thickness=1, color=grey))
    story.append(Paragraph("本报告由 AI 辅助设计系统自动生成，数据基于 3D 场景引擎。", ParagraphStyle('footer', fontName='CJK', fontSize=7, textColor=grey, alignment=TA_CENTER)))
    
    doc.build(story)
    return output_path

def _generate_html_report(scene, output_path, **kwargs):
    """Fallback HTML report when reportlab/CJK font unavailable."""
    rooms = [_n(r) for r in (get_rooms(scene))]
    total_area = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms)
    
    sections = []
    
    # Validation
    val = kwargs.get('validation')
    if val:
        sections.append(f"""<section><h2>Quality Check</h2>
        <div class="score">{val.score:.0f}<span>/100</span></div>
        <p>{'PASSED' if val.passed else 'FAILED'} | Errors: {len(val.errors)} | Warnings: {len(val.warnings)}</p></section>""")
    
    # Critique
    cr = kwargs.get('critique')
    if cr:
        items_html = ''.join(f'<li>[{i.cat}] {i.title}: {i.detail}</li>' for i in cr.items[:6])
        sections.append(f"""<section><h2>Design Critique</h2>
        <div class="score">{cr.score:.0f}<span>/100</span></div><p>{cr.summary}</p><ul>{items_html}</ul></section>""")
    
    # Cost
    cost = kwargs.get('cost')
    if cost:
        s = cost.get('summary',{})
        sections.append(f"""<section><h2>Budget</h2>
        <div class="total">Total</div><p>{s.get('grand_total',0):,.0f} ({s.get('per_sqm',0):,.0f}/m2)</p>
        <p>Hard: {s.get('hard_decoration',0):,.0f} | Soft: {s.get('soft_decoration',0):,.0f}</p></section>""")
    
    # Schedule
    sch = kwargs.get('schedule')
    if sch:
        tasks_html = ''.join(f'<li>{"[CP]" if t.is_critical else ""} {t.name}: {t.duration_days}d</li>' for t in sch.tasks)
        sections.append(f"""<section><h2>Schedule</h2><p>{sch.total_days} days | Critical: {len(sch.critical_path)} tasks</p><ul>{tasks_html}</ul></section>""")
    
    # Electrical
    e = kwargs.get('electrical')
    if e:
        sections.append(f"""<section><h2>Electrical</h2><p>{len(e.points)} points | {e.total_load_w}W | Main: {e.main_breaker_a}A</p></section>""")
    
    # MEP
    mep = kwargs.get('mep')
    if mep:
        sections.append(f"""<section><h2>MEP</h2><p>Plumbing: {len(mep.plumbing)}pts | HVAC: {len(mep.hvac)}zones | {mep.total_ac_capacity_kw}kW</p></section>""")
    
    # Daylight
    dl = kwargs.get('daylight')
    if dl:
        dl_html = ''.join(f'<li>{d.room_name}: {d.natural_light_score}/100 {"OK" if d.meets_standard else "NG"}</li>' for d in dl[:6])
        sections.append(f"""<section><h2>Daylight</h2><ul>{dl_html}</ul></section>""")
    
    # Energy
    en = kwargs.get('energy')
    if en:
        sections.append(f"""<section><h2>Energy</h2><p>Wall U={en.wall_u_value} | Heat={en.heating_load_kw}kW | Cool={en.cooling_load_kw}kW</p></section>""")
    
    # Feng Shui
    fs = kwargs.get('fengshui')
    if fs:
        sections.append(f"""<section><h2>Feng Shui</h2><p>{fs.overall} | Good: {fs.good_count} | Bad: {fs.bad_count}</p></section>""")
    
    # Fire
    fr = kwargs.get('fire_r')
    if fr:
        sections.append(f"""<section><h2>Fire Safety</h2><p>Pass: {fr.pass_count}/{len(fr.checks)} | Equipment: {len(fr.equipment_needed)} items</p></section>""")
    
    # Accessibility
    acc = kwargs.get('accessibility')
    if acc:
        sections.append(f"""<section><h2>Accessibility</h2><p>Score: {acc.score}/100</p></section>""")
    
    # Acoustic
    ac = kwargs.get('acoustic')
    if ac:
        sections.append(f"""<section><h2>Acoustics</h2><p>Overall: {'PASS' if ac.overall_pass else 'FAIL'}</p></section>""")
    
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>Design Report</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}} body{{font-family:'Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:20px;max-width:900px;margin:0 auto}}
h1{{text-align:center;padding:30px 0;color:#1a1a2e;font-size:24px}}
section{{background:#fff;border-radius:8px;padding:20px;margin:15px 0;box-shadow:0 2px 8px rgba(0,0,0,0.08)}}
h2{{color:#1a1a2e;font-size:16px;margin-bottom:10px;border-bottom:2px solid #4a90d9;padding-bottom:5px}}
.score{{display:inline-block;background:#4a90d9;color:#fff;font-size:28px;font-weight:bold;padding:8px 16px;border-radius:6px;margin:5px 0}}
.score span{{font-size:14px;opacity:0.8}}
p{{margin:5px 0;font-size:13px;line-height:1.6}}
ul{{list-style:none;padding-left:10px}}
li{{padding:3px 0;font-size:12px;border-bottom:1px dotted #eee}}
li:before{{content:"· ";color:#4a90d9;font-weight:bold}}
.footer{{text-align:center;color:#999;font-size:11px;padding:20px;margin-top:20px}}
</style></head><body>
<h1>Interior Design Comprehensive Report</h1>
<p style="text-align:center;color:#666">Area: {total_area:.1f}m2 | Rooms: {len(rooms)} | Date: {datetime.now().strftime('%Y-%m-%d')}</p>
{''.join(sections)}
<div class="footer">Generated by AI-Assisted Design System | Scene3D Engine</div>
</body></html>"""
    
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path