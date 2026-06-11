"""M4 Step 4: 给排水点位图"""
import json,os,sys
import ezdxf; from ezdxf.enums import TextEntityAlignment

def generate_plumbing_plan(conditions_json_path,dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f: conditions=json.load(f)
    base_dir=os.path.dirname(os.path.abspath(conditions_json_path))
    orig_dxf=os.path.join(base_dir,"原始结构底图.dxf")
    doc=ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp=doc.modelspace()
    for ln,c,lw in [("施工-给水管",5,35),("施工-排水管",1,35),("施工-给排水标注",5,9),("施工-施工说明",6,9)]:
        if ln not in [l.dxf.name for l in doc.layers]: doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})
    
    y=200
    msp.add_text("=== 给排水点位图 ===",height=400,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=80
    
    plumbing = [
        ("厨房", [("水槽给水",2,"冷热"),("水槽排水",1,"DN50"),("净水器",1,"建议预留"),("洗碗机",1,"给排水预留"),("前置过滤器",1,"入户总水管")]),
        ("卫生间", [("洗手台给水",2,"冷热"),("洗手台排水",1,"DN50"),("马桶给水",1,"DN15"),("马桶排水",1,"DN110"),("淋浴给水",2,"冷热"),("地漏",1,"DN50"),("洗衣机给水",1,"DN15"),("洗衣机排水",1,"DN50")]),
        ("阳台", [("洗衣机给水",1,"DN15"),("洗衣机排水",1,"DN50"),("拖把池给水",1,"DN15"),("地漏",1,"DN50")]),
    ]
    
    for room, items in plumbing:
        msp.add_text("【%s】"%room,height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=50
        for name,qty,note in items:
            line="%s %s x%d"%(name,note,qty)
            msp.add_text(line,height=180,dxfattribs={"layer":"施工-给排水标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT); y+=35
    
    y+=40
    specs=["给水管采用PPR管热熔连接","排水管采用UPVC管","给水管打压1.0MPa保压30分钟","排水管需做通球试验","卫生间防水做完后做闭水试验48h","热水管需做保温处理"]
    for s in specs:
        msp.add_text(s,height=180,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=30
    
    doc.saveas(dxf_output_path); return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../../templates/concept_output/给排水点位图.dxf"
    r=generate_plumbing_plan(inp,out);print("OK:",r)
