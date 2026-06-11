"""M4 Step 2: 砌墙图"""
import json,os,sys
import ezdxf; from ezdxf.enums import TextEntityAlignment

def generate_wall_plan(conditions_json_path,dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f: conditions=json.load(f)
    base_dir=os.path.dirname(os.path.abspath(conditions_json_path))
    orig_dxf=os.path.join(base_dir,"原始结构底图.dxf")
    doc=ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp=doc.modelspace()
    for ln,c,lw in [("施工-新砌墙体",6,50),("施工-砌墙标注",6,20),("施工-施工说明",6,9)]:
        if ln not in [l.dxf.name for l in doc.layers]: doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})
    y=200
    msp.add_text("=== 砌墙图 ===",height=400,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=80
    msp.add_text("本户型未规划拆改，如需新砌墙请在设计阶段确认",height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=80
    msp.add_text("砌墙标准做法:",height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
    specs=["新砌墙体采用120mm空心砖","底部砌3层实心砖做地枕","每50cm植入拉结筋","顶部斜砌塞实","新旧墙交接处挂钢丝网","抹灰前墙面充分润湿"]
    for s in specs:
        msp.add_text(s,height=180,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=30
    doc.saveas(dxf_output_path); return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../../templates/concept_output/砌墙图.dxf"
    r=generate_wall_plan(inp,out);print("OK:",r)
