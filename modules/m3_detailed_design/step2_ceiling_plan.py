"""M3 Step 2: 天花布置图
AI 看图(氛围图) + RoomPlan 数据 → 天花 DXF
"""
import json, os, sys, re
import dashscope
from dashscope import MultiModalConversation
import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DASHSCOPE_API_KEY

dashscope.api_key = DASHSCOPE_API_KEY

CEILING_PROMPT = """你是一个专业的室内设计师，在看一张室内效果图。
请根据这张图，分析天花（吊顶）的设计，输出以下信息：
1. 吊顶类型（平顶/局部吊顶/全吊顶/无吊顶）
2. 灯具类型和位置（吸顶灯/筒灯/轨道灯/灯带/吊灯）
3. 空调出风口位置（如有）
4. 横梁处理方式（包梁/裸露/吊顶隐藏）

按以下JSON格式输出（只输出JSON）：
{"ceiling_type":"吊顶类型","lights":[{"type":"筒灯","count":6,"arrangement":"四周均匀分布"}],"ac_vent":"空调出风口位置描述","beam_treatment":"横梁处理","notes":"其他说明"}
"""


def analyze_ceiling(image_path):
    """Qwen-VL 看图分析天花"""
    resp = MultiModalConversation.call(
        model="qwen-vl-plus",
        messages=[{
            "role":"user",
            "content":[
                {"text": CEILING_PROMPT},
                {"image": "file://%s" % image_path}
            ]
        }]
    )

    content = resp.output.choices[0].message.content
    if isinstance(content, list):
        text = "".join(c.get("text","") for c in content)
    else:
        text = str(content)

    try:
        return json.loads(text)
    except:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        return {"raw": text}


def generate_ceiling_plan(conditions_json_path, dxf_output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    space = conditions.get("space_data", {})

    # 找氛围图
    atmos_files = {f.replace("氛围图.png",""): os.path.join(out_dir, f)
                   for f in os.listdir(out_dir) if "氛围图" in f and f.endswith(".png")}

    # 加载底图
    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    # 新增天花图层
    for ln, c, lw in [("深化-天花吊顶", 6, 35), ("深化-灯具定位", 2, 20),
                      ("深化-空调定位", 4, 20), ("深化-天花标注", 6, 9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color":c, "lineweight":lw})

    y_pos = 200
    msp.add_text("=== 天花布置图 ===", height=350,
                dxfattribs={"layer":"深化-天花标注"}).set_placement((200,y_pos), align=TextEntityAlignment.LEFT)
    y_pos += 80

    for rm in space.get("rooms", []):
        img_path = atmos_files.get(rm["name"])
        if not img_path or not os.path.exists(img_path):
            continue

        print("  分析 %s 天花..." % rm["name"])
        result = analyze_ceiling(img_path)

        # 写房间名
        msp.add_text("【%s】天花" % rm["name"], height=300,
                    dxfattribs={"layer":"深化-天花标注"}).set_placement((200,y_pos), align=TextEntityAlignment.LEFT)
        y_pos += 60

        # 吊顶类型
        ct = result.get("ceiling_type","未识别")
        msp.add_text("吊顶: %s" % ct, height=200,
                    dxfattribs={"layer":"深化-天花吊顶"}).set_placement((250,y_pos), align=TextEntityAlignment.LEFT)
        y_pos += 40

        # 灯具
        lights = result.get("lights",[])
        for lt in lights:
            text = "%s x%d" % (lt.get("type","灯"), lt.get("count",1))
            arr = lt.get("arrangement","")
            if arr: text += " (%s)" % arr
            msp.add_text(text, height=180,
                        dxfattribs={"layer":"深化-灯具定位"}).set_placement((250,y_pos), align=TextEntityAlignment.LEFT)
            y_pos += 35

        # 空调
        ac = result.get("ac_vent","")
        if ac:
            msp.add_text("空调: %s" % ac[:40], height=180,
                        dxfattribs={"layer":"深化-空调定位"}).set_placement((250,y_pos), align=TextEntityAlignment.LEFT)
            y_pos += 35

        # 梁处理
        bt = result.get("beam_treatment","")
        if bt:
            msp.add_text("梁处理: %s" % bt[:40], height=180,
                        dxfattribs={"layer":"深化-天花标注"}).set_placement((250,y_pos), align=TextEntityAlignment.LEFT)
            y_pos += 35

        y_pos += 40

    # 绘制简单的天花范围（在房间区域内画矩形示意）
    if space.get("rooms"):
        y_pos2 = y_pos + 60
        msp.add_text("平面示意（灯具位置仅供参考，设计师精确调整）", height=180,
                    dxfattribs={"layer":"深化-天花标注"}).set_placement((200,y_pos2), align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)
    return dxf_output_path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv)>2 else "../templates/concept_output/天花布置图.dxf"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = generate_ceiling_plan(inp, out)
    print("OK:", r)

