"""M4 Step 6: 材质标注图"""
import json,os,sys
import ezdxf; from ezdxf.enums import TextEntityAlignment

def generate_material_plan(conditions_json_path,dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f: conditions=json.load(f)
    base_dir=os.path.dirname(os.path.abspath(conditions_json_path))
    orig_dxf=os.path.join(base_dir,"原始结构底图.dxf")
    doc=ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp=doc.modelspace()
    for ln,c,lw in [("施工-地面标注",3,35),("施工-墙面标注",5,35),("施工-天花标注",6,35),("施工-材质索引",2,9),("施工-施工说明",6,9)]:
        if ln not in [l.dxf.name for l in doc.layers]: doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})
    
    y=200
    msp.add_text("=== 全房材质标注图 ===",height=400,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=80
    
    style=conditions.get("style",{})
    floor_def=style.get("floor_material","木地板")
    wall_def=style.get("wall_material","乳胶漆")
    
    materials = [
        ("客厅", floor_def+"通铺","暖灰微水泥","乳胶漆白色","木格栅"),
        ("厨房","防滑瓷砖","手工砖/半墙","铝扣板吊顶","岩板台面"),
        ("主卧",floor_def+"通铺","艺术涂料","乳胶漆白色","硬包床头"),
        ("卫生间","防滑瓷砖","水磨石瓷砖","铝扣板","—"),
    ]
    
    msp.add_text("%-12s %-16s %-16s %-16s %s" % ("房间","地面","墙面","天花","背景墙"),
                height=220,dxfattribs={"layer":"施工-材质索引"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
    
    for rm, floor,wall,ceil,feature in materials:
        msp.add_text("%-12s %-16s %-16s %-16s %s"%(rm,floor,wall,ceil,feature),
                    height=200,dxfattribs={"layer":"施工-材质索引"}).set_placement((220,y),align=TextEntityAlignment.LEFT); y+=40
    
    y+=40
    msp.add_text("施工说明:",height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
    notes=["所有材料品牌/型号以材料清单为准","施工前需确认材料到货情况","不同材料交接处需做收口处理","瓷砖留缝2mm，使用十字卡","木地板预留8-10mm伸缩缝"]
    for n in notes:
        msp.add_text(n,height=180,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=30
    
    doc.saveas(dxf_output_path); return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../../templates/concept_output/材质标注图.dxf"
    r=generate_material_plan(inp,out);print("OK:",r)
