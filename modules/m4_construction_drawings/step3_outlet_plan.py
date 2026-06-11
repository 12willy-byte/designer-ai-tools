"""M4 Step 2: 插座点位图"""
import json,os,sys,math
import ezdxf; from ezdxf.enums import TextEntityAlignment

def generate_outlet_plan(conditions_json_path,dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f: conditions=json.load(f)
    base_dir=os.path.dirname(os.path.abspath(conditions_json_path))
    orig_dxf=os.path.join(base_dir,"原始结构底图.dxf")
    doc=ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp=doc.modelspace()
    for ln,c,lw in [("施工-插座定位",4,35),("施工-开关定位",2,35),("施工-电气标注",4,9),("施工-施工说明",6,9)]:
        if ln not in [l.dxf.name for l in doc.layers]: doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})
    
    y=200
    msp.add_text("=== 插座点位图 ===",height=400,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=80
    
    # 每个房间标准化布点
    rooms_data = [
        ("客厅", [("电视插座",4,"东墙"),("沙发旁USB",2,"西墙"),("空调插座",1,"南墙"),("地插",1,"茶几位置"),("网络口",1,"电视墙")]),
        ("厨房", [("台面插座",4,"北墙"),("油烟机插座",1,"吊顶"),("冰箱插座",1,"入口侧"),("水槽下插座",2,"供给净水/垃圾处理器"),("嵌入式插座",2,"高柜")]),
        ("主卧", [("床头插座x2",4,"床两侧"),("电视插座",2,"床对面"),("空调插座",1,"靠窗侧"),("书桌插座",3,"书桌位置")]),
        ("卫生间", [("镜前灯/吹风",2,"洗手台旁"),("智能马桶",1,"马桶旁"),("热水器",1,"淋浴区外"),("暖风机",1,"吊顶")]),
    ]
    
    for room, outlets in rooms_data:
        msp.add_text("【%s】"%room,height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
        for name,qty,pos in outlets:
            msp.add_text("%s x%d (%s)"%(name,qty,pos),height=180,dxfattribs={"layer":"施工-插座定位"}).set_placement((250,y),align=TextEntityAlignment.LEFT); y+=35
    
    y+=40
    msp.add_text("标准要求:",height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
    specs=["插座距地300mm","开关距地1300mm","厨房台面插座距台面150mm","空调插座距地2200mm","卫生间插座带防溅盒","所有回路需配漏电保护"]
    for s in specs:
        msp.add_text(s,height=180,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=30
    
    doc.saveas(dxf_output_path); return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../../templates/concept_output/插座点位图.dxf"
    r=generate_outlet_plan(inp,out);print("OK:",r)
