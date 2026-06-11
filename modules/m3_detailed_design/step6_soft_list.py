"""M3 Step 6: 软装清单生成
DeepSeek 根据风格/色彩/材质推荐软装选型
"""
import json, os, sys, re
from openai import OpenAI
import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

SYSTEM_PROMPT = """你是一个资深软装搭配师。根据设计条件，为每个空间推荐软装选型清单。

按以下JSON格式输出（只输出JSON）：
{"soft_furnishings":[{"room":"客厅","items":[{"category":"沙发","name":"现代简约布艺沙发","spec":"2200×900×750mm","color":"米灰色","material":"棉麻","qty":1,"reference_brand":"参考品牌：北欧风情"}],"total_estimated_budget":"约15000元"}],"design_notes":"搭配建议"}
"""


def generate_soft_list(conditions_json_path, dxf_output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    style = conditions.get("style", {})
    space = conditions.get("space_data", {})
    rooms_req = conditions.get("rooms_requirements", {})

    prompt = "请为以下项目推荐软装清单：\n\n风格: %s\n色调: %s\n关键词: %s\n\n" % (
        style.get("primary_style",""), style.get("color_tone",""), style.get("keywords",""))

    for rm in space.get("rooms", []):
        prompt += "\n【%s】%d×%dmm" % (rm["name"], rm["width_mm"], rm["height_mm"])
        req = rooms_req.get(rm["name"], {})
        for k, v in req.items():
            if v: prompt += "  %s: %s" % (k, v)

    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": prompt}],
        temperature=0.6, max_tokens=3000,
    )

    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        data = json.loads(m.group(1)) if m else {"soft_furnishings": []}

    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    for ln, c, lw in [("深化-软装清单", 6, 20), ("深化-软装标注", 5, 9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color": c, "lineweight": lw})

    y = 200
    msp.add_text("=== 软装选型清单 ===", height=350,
                dxfattribs={"layer": "深化-软装清单"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 80

    for sf in data.get("soft_furnishings", []):
        room = sf.get("room", "")
        msp.add_text("【%s】" % room, height=250,
                    dxfattribs={"layer": "深化-软装清单"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
        y += 50

        for item in sf.get("items", []):
            cat = item.get("category", "")
            name = item.get("name", "")
            spec = item.get("spec", "")
            color = item.get("color", "")
            mat = item.get("material", "")
            qty = item.get("qty", 1)
            text = "%s: %s  %s" % (cat, name, spec)
            if color: text += " %s" % color
            if mat: text += " %s" % mat
            text += " x%d" % qty

            msp.add_text(text, height=180,
                        dxfattribs={"layer": "深化-软装标注"}).set_placement((250, y), align=TextEntityAlignment.LEFT)
            y += 35

            brand = item.get("reference_brand", "")
            if brand:
                msp.add_text("  %s" % brand, height=150,
                            dxfattribs={"layer": "深化-软装标注"}).set_placement((250, y), align=TextEntityAlignment.LEFT)
                y += 30
        y += 30

    notes = data.get("design_notes", "")
    if notes:
        y += 20
        msp.add_text("搭配建议: %s" % notes[:80], height=200,
                    dxfattribs={"layer": "深化-软装清单"}).set_placement((200, y), align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)

    # 也保存 JSON
    out_dir = os.path.join(base_dir, "concept_output")
    json_path = os.path.join(out_dir, "软装清单.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return dxf_output_path, json_path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "../templates/concept_output/软装清单.dxf"
    r, j = generate_soft_list(inp, out)
    print("DXF:", r)
    print("JSON:", j)
