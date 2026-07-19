"""
Step 5: 功能布局建议生成器 (v2)
使用统一 AI 客户端
"""
import json, os, sys, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from core.ai_client import get_client
from core.design_schema import normalize_conditions

SYSTEM_PROMPT = """你是中国顶尖的室内设计布局规划专家。根据结构化的3D空间数据，做出合理的功能布局建议。

严格按 JSON 格式输出：
{
  "layout_name": "方案A",
  "description": "方案核心理念",
  "rooms": [
    {
      "name": "客厅",
      "analysis": "空间分析",
      "layout_suggestions": ["建议1", "建议2"],
      "furniture_suggestions": [{"item":"沙发","suggested_size":"2800x1800","material":"灰色布艺"}],
      "notes": "注意事项"
    }
  ],
  "circulation_analysis": "整体动线分析",
  "design_highlights": ["亮点1"]
}

【事实与假设边界 — 必须严格遵守】
1. rooms 只覆盖输入中列出的房间，房间名称与数量以输入为准，不得新增、合并或改写输入中不存在的空间。
2. 家具与材料只描述品类/尺寸/材质，禁止编造具体品牌名和型号；如举例必须标注"示例品牌，可替换"。
3. 输入未直接给出的信息（家庭成员年龄推断、未确认的现场条件等）如需引用，以"假设："开头标注，不得与事实混排。"""


def generate_layout(conditions_json_path: str, dxf_input_path: str = None, dxf_output_path: str = None) -> dict:
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = normalize_conditions(json.load(f))

    space = conditions.get("space_data", {})
    rooms_req = conditions.get("rooms_requirements", {})
    style = conditions.get("style", {})

    lines = ["=== 项目概况 ==="]
    lines.append("风格: %s" % style.get("primary_style", "未指定"))
    lines.append("色调: %s" % style.get("color_tone", "未指定"))
    lines.append("关键词: %s" % style.get("keywords", ""))
    lines.append("")

    if space.get("rooms"):
        lines.append("=== 各房间三维数据 ===")
        for rm in space["rooms"]:
            lines.append("【%s】面积: %.1f m2, 尺寸: %d x %d mm" % (
                rm["name"], rm["area_m2"], rm["width_mm"], rm["height_mm"]))
            req = rooms_req.get(rm["name"], {})
            if req:
                lines.append("  客户要求:")
                for k, v in req.items():
                    if v:
                        lines.append("    - %s: %s" % (k, v))

    if space.get("has_beams"):
        lines.append("\n有梁结构，吊顶需考虑")
    if space.get("has_columns"):
        lines.append("有结构柱，需考虑包柱设计")

    spatial_text = "\n".join(lines)
    client = get_client()
    data = client.chat_json(SYSTEM_PROMPT, spatial_text, temperature=0.6, max_tokens=3000)

    # 写入 DXF
    if dxf_output_path:
        _write_dxf(data, dxf_input_path, dxf_output_path)

    return data


def _write_dxf(data: dict, dxf_input_path: str, dxf_output_path: str):
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    if dxf_input_path and os.path.exists(dxf_input_path):
        doc = ezdxf.readfile(dxf_input_path)
    else:
        doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    layers = {
        "AI-布局建议": {"color": 4, "lw": 35},
        "AI-功能分区": {"color": 5, "lw": 20},
        "AI-家具建议": {"color": 6, "lw": 20},
    }
    for ln, lp in layers.items():
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color": lp["color"], "lineweight": lp["lw"]})

    y = 4500
    msp.add_text("布局方案: %s" % data.get("layout_name", ""), height=350,
                 dxfattribs={"layer": "AI-布局建议"}).set_placement((0, y), align=TextEntityAlignment.LEFT)
    y -= 400
    msp.add_text(data.get("description", ""), height=250,
                 dxfattribs={"layer": "AI-布局建议"}).set_placement((0, y), align=TextEntityAlignment.LEFT)

    for rm in data.get("rooms", []):
        y -= 350
        msp.add_text("[%s]" % rm.get("name", ""), height=280,
                     dxfattribs={"layer": "AI-功能分区"}).set_placement((0, y), align=TextEntityAlignment.LEFT)
        for suggestion in rm.get("layout_suggestions", []):
            y -= 220
            msp.add_text("  - %s" % suggestion, height=200,
                         dxfattribs={"layer": "AI-家具建议"}).set_placement((50, y), align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    result = generate_layout(inp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
