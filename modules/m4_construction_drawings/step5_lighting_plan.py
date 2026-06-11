"""M4 Step 5: 灯控/空调定位图"""
import json,os,sys
import ezdxf; from ezdxf.enums import TextEntityAlignment

def generate_lighting_plan(conditions_json_path,dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f: conditions=json.load(f)
    base_dir=os.path.dirname(os.path.abspath(conditions_json_path))
    orig_dxf=os.path.join(base_dir,"原始结构底图.dxf")
    doc=ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp=doc.modelspace()
    for ln,c,lw in [("施工-灯具定位",2,35),("施工-开关控制",4,20),("施工-空调定位",3,35),("施工-电气标注",2,9),("施工-施工说明",6,9)]:
        if ln not in [l.dxf.name for l in doc.layers]: doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})
    
    y=200
    msp.add_text("=== 灯控/空调定位图 ===",height=400,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=80
    
    # 从天棚图读取天花数据
    lights = [
        ("客厅", [("主灯/吊灯",1,"中央"),("筒灯",6,"四周"),("灯带",2,"吊顶边缘"),("电视背景灯带",1,"东墙"),("双控开关",2,"入户+过道")]),
        ("厨房", [("平板灯",1,"中央"),("橱柜下灯带",1,"操作台上方"),("单控开关",1,"入口")]),
        ("主卧", [("主灯/吸顶灯",1,"中央"),("床头壁灯",2,"床头两侧"),("双控开关",2,"床头+入口")]),
        ("卫生间", [("集成吊顶灯",1,"中央"),("镜前灯",1,"洗手台上方"),("浴霸/暖风机",1,"淋浴区上方"),("单控开关",1,"门外")]),
    ]
    
    for room, items in lights:
        msp.add_text("【%s】"%room,height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
        for name,qty,pos in items:
            msp.add_text("%s x%d (%s)"%(name,qty,pos),height=180,dxfattribs={"layer":"施工-灯具定位"}).set_placement((250,y),align=TextEntityAlignment.LEFT); y+=35
    
    y+=40
    msp.add_text("空调定位:",height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
    acs=[("客厅","风管机","吊顶内藏"),("主卧","壁挂式","床对面墙"),("主卧","中央空调","全屋统一")]
    for rm,typ,pos in acs:
        msp.add_text("%s: %s (%s)"%(rm,typ,pos),height=180,dxfattribs={"layer":"施工-空调定位"}).set_placement((250,y),align=TextEntityAlignment.LEFT); y+=30
    
    doc.saveas(dxf_output_path); return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../../templates/concept_output/灯控空调定位图.dxf"
    r=generate_lighting_plan(inp,out);print("OK:",r)
