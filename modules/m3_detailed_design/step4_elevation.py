"""M3 Step 4: 立面图生成
AI 看图 + RoomPlan → 各墙面立面 DXF
"""
import json,os,sys,re
import dashscope
from dashscope import MultiModalConversation
import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from config import DASHSCOPE_API_KEY
dashscope.api_key = DASHSCOPE_API_KEY

ELEVATION_PROMPT = """你是一个专业的室内设计师，在看一张室内效果图。
分析图中可见的墙面设计，输出以下信息（JSON格式）：
{"walls":[{"position":"墙面位置","width_mm":0,"height_mm":0,"material":"材质","color":"颜色","features":["设计元素1","设计元素2"],"electrical":["插座/开关位置"]}],"overall_style":"整体墙面风格"}
只输出JSON，不要多余文字。
"""

def analyze_elevation(image_path):
    resp = MultiModalConversation.call(model="qwen-vl-plus",messages=[{"role":"user","content":[{"text":ELEVATION_PROMPT},{"image":"file://%s"%image_path}]}])
    c = resp.output.choices[0].message.content
    text = "".join(c.get("text","") for c in c) if isinstance(c,list) else str(c)
    try: return json.loads(text)
    except:
        m=re.search(r"```(?:json)?\s*(\{.*?\})\s*```",text,re.DOTALL)
        return json.loads(m.group(1)) if m else {"raw":text}

def generate_elevation(conditions_json_path,dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f: conditions=json.load(f)
    base_dir=os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir=os.path.join(base_dir,"concept_output")
    space=conditions.get("space_data",{})

    atmos_files={f.replace("氛围图.png",""):os.path.join(out_dir,f) for f in os.listdir(out_dir) if "氛围图" in f and f.endswith(".png")}

    orig_dxf=os.path.join(base_dir,"原始结构底图.dxf")
    doc=ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp=doc.modelspace()

    for ln,c,lw in [("深化-立面轮廓",7,50),("深化-立面材质",5,20),("深化-立面标注",2,9),("深化-电气定位",4,20)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})

    y=200
    msp.add_text("=== 立面图索引 ===",height=400,dxfattribs={"layer":"深化-立面标注"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y+=100

    for rm in space.get("rooms",[]):
        img=atmos_files.get(rm["name"])
        if not img or not os.path.exists(img): continue

        print("  分析 %s 立面..."%rm["name"])
        r=analyze_elevation(img)

        walls=r.get("walls",[])
        msp.add_text("【%s】%d面墙"%(rm["name"],len(walls)),height=300,dxfattribs={"layer":"深化-立面标注"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
        y+=60

        for w in walls:
            pos=w.get("position","")
            mat=w.get("material","")
            col=w.get("color","")
            h=w.get("height_mm","")
            text="%s: %s %s"%(pos,mat,col)
            if h:text+=" %dmm"%h
            msp.add_text(text,height=200,dxfattribs={"layer":"深化-立面材质"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
            y+=35

            features=w.get("features",[])
            for f in features:
                msp.add_text("  - %s"%f,height=150,dxfattribs={"layer":"深化-立面标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
                y+=30

            elec=w.get("electrical",[])
            for e in elec:
                msp.add_text("  [电气] %s"%e,height=150,dxfattribs={"layer":"深化-电气定位"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
                y+=30
            y+=20

    style=r.get("overall_style","")
    if style:
        msp.add_text("整体风格: %s"%style,height=250,dxfattribs={"layer":"深化-立面标注"}).set_placement((200,y),align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)
    return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../templates/concept_output/立面图.dxf"
    os.makedirs(os.path.dirname(out),exist_ok=True)
    r=generate_elevation(inp,out);print("OK:",r)
