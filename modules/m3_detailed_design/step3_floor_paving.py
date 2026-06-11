"""M3 Step 3: 地面铺装图
AI 看图 + RoomPlan 数据 → 地面铺装 DXF
"""
import json, os, sys, re
import dashscope
from dashscope import MultiModalConversation
import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DASHSCOPE_API_KEY
dashscope.api_key = DASHSCOPE_API_KEY

FLOOR_PROMPT = """你是一个专业的室内设计师，在看一张室内效果图。
分析地面设计，输出以下信息（JSON格式）：
{"floor_material":"地面材质","paving_pattern":"铺贴方式","color":"颜色","zone_divisions":[{"area":"区域名","material":"材质","note":"说明"}],"baseboard":"踢脚线材质和高度","notes":"其他说明"}
"""


def analyze_floor(image_path):
    resp = MultiModalConversation.call(
        model="qwen-vl-plus",
        messages=[{"role":"user","content":[{"text":FLOOR_PROMPT},{"image":"file://%s"%image_path}]}])
    c = resp.output.choices[0].message.content
    text = "".join(c.get("text","") for c in c) if isinstance(c,list) else str(c)
    try: return json.loads(text)
    except:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```",text,re.DOTALL)
        return json.loads(m.group(1)) if m else {"raw":text}


def generate_floor_plan(conditions_json_path, dxf_output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    space = conditions.get("space_data", {})

    atmos_files = {f.replace("氛围图.png",""): os.path.join(out_dir, f)
                   for f in os.listdir(out_dir) if "氛围图" in f and f.endswith(".png")}

    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    for ln,c,lw in [("深化-铺装分区",8,35),("深化-铺装标注",8,9),("深化-材料标注",3,9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})

    y = 200
    msp.add_text("=== 地面铺装图 ===",height=350,dxfattribs={"layer":"深化-铺装标注"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 80

    for rm in space.get("rooms",[]):
        img = atmos_files.get(rm["name"])
        if not img or not os.path.exists(img): continue

        print("  分析 %s 地面..." % rm["name"])
        r = analyze_floor(img)

        msp.add_text("【%s】地面" % rm["name"],height=300,dxfattribs={"layer":"深化-铺装标注"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
        y += 60
        msp.add_text("材质: %s" % r.get("floor_material",""),height=200,dxfattribs={"layer":"深化-材料标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
        y += 40
        msp.add_text("铺贴: %s" % r.get("paving_pattern",""),height=200,dxfattribs={"layer":"深化-铺装标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
        y += 40

        zones = r.get("zone_divisions",[])
        for z in zones:
            msp.add_text("  %s: %s" % (z.get("area",""),z.get("material","")),height=180,dxfattribs={"layer":"深化-铺装分区"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
            y += 35

        bb = r.get("baseboard","")
        if bb:
            msp.add_text("踢脚线: %s" % bb[:40],height=180,dxfattribs={"layer":"深化-材料标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
            y += 35

        # 面积计算
        area = next((rm2["area_m2"] for rm2 in space["rooms"] if rm2["name"]==rm["name"]),0)
        if area:
            msp.add_text("面积: %.1f m2  需采购: %.1f m2 (含5%%损耗)" % (area,area*1.05),
                        height=180,dxfattribs={"layer":"深化-材料标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
            y += 35
        y += 40

    doc.saveas(dxf_output_path)
    return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../templates/concept_output/地面铺装图.dxf"
    os.makedirs(os.path.dirname(out),exist_ok=True)
    r=generate_floor_plan(inp,out);print("OK:",r)
