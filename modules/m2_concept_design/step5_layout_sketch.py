"""Step 5: 功能布局建议生成器
DeepSeek 基于 RoomPlan 3D 结构化数据分析空间 → 输出文字布局建议到 DXF
"""
import json, os, sys, re
from openai import OpenAI
import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

SYSTEM_PROMPT = """你是中国顶尖的室内设计布局规划专家。你擅长阅读结构化的3D空间数据，为客户做出合理的功能布局建议。

输入数据包含每个房间的精确尺寸（毫米级）、门窗位置、梁柱位置。
请仔细分析空间关系，给出合理的布局建议。

请按以下 JSON 格式输出（只输出 JSON，不要多余文字）：

{
  "layout_name": "方案A",
  "description": "方案核心理念一句话",
  "rooms": [
    {
      "name": "客厅",
      "analysis": "空间分析（墙面关系、采光方向、通道）",
      "layout_suggestions": [
        "沙发靠西墙放置，L型布艺沙发，尺寸建议2800×1800",
        "电视墙设在东墙做整面收纳柜，深度400mm，搭配投影幕布",
        "南侧落地窗前保留1200mm通道，保持采光通透"
      ],
      "furniture_suggestions": [
        {"item":"L型沙发","suggested_size":"2800×1800","material":"灰色布艺"},
        {"item":"茶几","suggested_size":"1200×600","material":"岩板"},
        {"item":"电视柜","suggested_size":"3000×400","material":"悬空木制"}
      ],
      "notes": "特殊注意事项"
    }
  ],
  "circulation_analysis": "整体动线分析",
  "design_highlights": ["亮点1", "亮点2"]
}
"""


def format_spatial_data(conditions):
    """把 RoomPlan JSON 转成 DeepSeek 能理解的空间描述"""
    space = conditions.get("space_data", {})
    rooms_req = conditions.get("rooms_requirements", {})
    style = conditions.get("style", {})

    lines = []
    lines.append("=== 项目概况 ===")
    lines.append("风格: %s" % style.get("primary_style","未指定"))
    lines.append("色调: %s" % style.get("color_tone","未指定"))
    lines.append("关键词: %s" % style.get("keywords",""))
    lines.append("")

    if space.get("rooms"):
        lines.append("=== 各房间三维数据（毫米级） ===")
        for rm in space["rooms"]:
            lines.append("")
            lines.append("【%s】面积: %.1f m2" % (rm["name"], rm["area_m2"]))
            lines.append("  尺寸: 长 %dmm × 宽 %dmm × 层高 2800mm" % (
                rm["width_mm"], rm["height_mm"]))
            lines.append("  墙面数: %d 面" % rm.get("wall_count",0))

            # 从原始 RoomPlan 获取更详细的数据
            req = rooms_req.get(rm["name"], {})
            if req:
                lines.append("  客户要求:")
                for k, v in req.items():
                    if v: lines.append("    - %s: %s" % (k, v))

    if space.get("has_beams"):
        lines.append("\n⚠ 存在梁结构，吊顶/布局需考虑梁的位置")
    if space.get("has_columns"):
        lines.append("⚠ 存在结构柱，需考虑包柱或绕柱设计")

    return "\n".join(lines)


def generate_layout(conditions_json_path, dxf_input_path, dxf_output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    # 格式化空间数据
    spatial_text = format_spatial_data(conditions)

    # 调用 DeepSeek
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":spatial_text},
        ],
        temperature=0.6,
        max_tokens=3000,
    )

    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
        else:
            data = {"rooms":[], "layout_name":"解析失败"}

    # 写入 DXF（新增 AI 方案图层）
    if dxf_input_path and os.path.exists(dxf_input_path):
        doc = ezdxf.readfile(dxf_input_path)
    else:
        doc = ezdxf.new("R2010")

    msp = doc.modelspace()

    # 新增布局建议图层
    layout_layers = {
        "AI方案-布局建议": {"color": 4, "lw": 35},  # 青色
        "AI方案-功能分区": {"color": 5, "lw": 20},  # 蓝色
        "AI方案-家具建议": {"color": 6, "lw": 20},  # 品红
        "AI方案-动线分析": {"color": 2, "lw": 15},  # 黄色
    }
    for ln, lp in layout_layers.items():
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color": lp["color"], "lineweight": lp["lw"]})

    # 写布局建议到 DXF
    x_pos = 200
    y_pos = 200
    line_h = 50

    # 方案标题
    msp.add_text("【AI 布局建议】%s" % data.get("layout_name","方案A"),
                 height=400, dxfattribs={"layer":"AI方案-布局建议"}
                ).set_placement((x_pos, y_pos), align=TextEntityAlignment.LEFT)
    y_pos += 100

    desc = data.get("description","")
    if desc:
        msp.add_text("核心理念: %s" % desc,
                     height=250, dxfattribs={"layer":"AI方案-布局建议"}
                    ).set_placement((x_pos, y_pos), align=TextEntityAlignment.LEFT)
        y_pos += 80

    # 逐房间
    for rm in data.get("rooms", []):
        y_pos += 60
        msp.add_text("▶ %s" % rm.get("name",""),
                     height=300, dxfattribs={"layer":"AI方案-功能分区"}
                    ).set_placement((x_pos, y_pos), align=TextEntityAlignment.LEFT)
        y_pos += 60

        for sug in rm.get("layout_suggestions", []):
            msp.add_text("  %s" % sug[:80],
                         height=200, dxfattribs={"layer":"AI方案-功能分区"}
                        ).set_placement((x_pos, y_pos+20), align=TextEntityAlignment.LEFT)
            y_pos += 45

        # 家具建议
        y_pos += 20
        for f in rm.get("furniture_suggestions", []):
            size = f.get("suggested_size","")
            mat = f.get("material","")
            text = "  %s" % f.get("item","")
            if size: text += "  [%s]" % size
            if mat: text += "  %s" % mat
            msp.add_text(text, height=200,
                        dxfattribs={"layer":"AI方案-家具建议"}
                        ).set_placement((x_pos, y_pos+20), align=TextEntityAlignment.LEFT)
            y_pos += 40

        notes = rm.get("notes","")
        if notes:
            msp.add_text("  ⚠ %s" % notes[:60], height=180,
                        dxfattribs={"layer":"AI方案-布局建议"}
                        ).set_placement((x_pos, y_pos+20), align=TextEntityAlignment.LEFT)
            y_pos += 40

    # 动线分析
    circ = data.get("circulation_analysis","")
    if circ:
        y_pos += 60
        msp.add_text("动线分析:", height=250,
                    dxfattribs={"layer":"AI方案-动线分析"}
                    ).set_placement((x_pos, y_pos), align=TextEntityAlignment.LEFT)
        y_pos += 55
        msp.add_text("  %s" % circ[:100], height=200,
                    dxfattribs={"layer":"AI方案-动线分析"}
                    ).set_placement((x_pos, y_pos), align=TextEntityAlignment.LEFT)

    # 设计亮点
    highlights = data.get("design_highlights", [])
    if highlights:
        y_pos += 80
        msp.add_text("设计亮点:", height=250,
                    dxfattribs={"layer":"AI方案-布局建议"}
                    ).set_placement((x_pos, y_pos), align=TextEntityAlignment.LEFT)
        y_pos += 55
        for h in highlights:
            msp.add_text("  %s" % h, height=200,
                        dxfattribs={"layer":"AI方案-布局建议"}
                        ).set_placement((x_pos, y_pos), align=TextEntityAlignment.LEFT)
            y_pos += 40

    doc.saveas(dxf_output_path)
    data["dxf_path"] = dxf_output_path
    return data


def main():
    inp = sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    dxf_in = sys.argv[2] if len(sys.argv)>2 else "../templates/原始结构底图.dxf"
    dxf_out = sys.argv[3] if len(sys.argv)>3 else "../templates/concept_output/布局方案.dxf"
    os.makedirs(os.path.dirname(dxf_out), exist_ok=True)

    r = generate_layout(inp, dxf_in, dxf_out)
    print("方案: %s" % r.get("layout_name",""))
    print("核心理念: %s" % r.get("description",""))
    print("房间数: %d" % len(r.get("rooms",[])))
    for rm in r.get("rooms",[]):
        print("  %s: %d 条布局建议, %d 件家具建议" % (
            rm.get("name",""),
            len(rm.get("layout_suggestions",[])),
            len(rm.get("furniture_suggestions",[]))))
    print("动线: %s" % r.get("circulation_analysis","")[:60])
    print("DXF:", r.get("dxf_path",""))


if __name__ == "__main__":
    main()
