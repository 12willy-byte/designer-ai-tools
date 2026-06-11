"""M7: 软装摆场与交付
家具清单、摆场方案、验收报告、实景存档
"""
import json, os, sys
from collections import OrderedDict
import ezdxf
from ezdxf.enums import TextEntityAlignment

def generate_delivery_plan(conditions_json_path, dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f:
        conditions = json.load(f)

    project = conditions.get("project",{})
    style = conditions.get("style",{})
    space = conditions.get("space_data",{})
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")

    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    for ln,c,lw in [("交付-软装清单",5,35),("交付-验收项",3,20),("交付-交付说明",6,9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})

    y = 200
    msp.add_text("=== 软装摆场与交付方案 ===",height=400,
                dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=80

    msp.add_text("项目: %s" % project.get("name","未命名"),height=250,
                dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=60

    # 1. 软装摆放清单
    msp.add_text("一、软装进场清单",height=300,
                dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=60

    furniture_list = [
        ("客厅",[("沙发","1件","靠西墙摆放"),("茶几","1件","沙发前方"),("电视柜","1件","东墙"),("地毯","1块","茶几下方"),("落地灯","2盏","沙发两侧"),("窗帘","1组","落地帘")]),
        ("餐厅",[("餐桌","1张","居中"),("餐椅","4把","餐桌四周"),("吊灯","1盏","餐桌上方")]),
        ("主卧",[("双人床","1张","靠北墙"),("床头柜","2个","床两侧"),("衣柜","1组","靠西墙"),("梳妆台","1张","靠东墙"),("窗帘","1组","遮光帘")]),
        ("厨房",[("橱柜","1套","U型"),("冰箱","1台","入口侧"),("烟机灶具","1套","东墙")]),
        ("卫生间",[("洗手台","1套","入门侧"),("马桶","1个","马桶区"),("淋浴屏","1套","淋浴区"),("镜柜","1个","洗手台上方")]),
    ]

    for room, items in furniture_list:
        msp.add_text("【%s】" % room,height=220,
                    dxfattribs={"layer":"交付-软装清单"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=40
        for name,qty,pos in items:
            msp.add_text("  %s: %s, %s" % (name,qty,pos),height=180,
                        dxfattribs={"layer":"交付-软装清单"}).set_placement((250,y),align=TextEntityAlignment.LEFT); y+=30
        y+=10

    # 2. 摆场顺序
    y+=20
    msp.add_text("二、摆场顺序",height=300,
                dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=60
    steps=["1. 开荒保洁 → 全房清洁","2. 家具进场 → 按平面图摆放","3. 窗帘安装 → 挂装调整",
           "4. 灯具安装 → 通电测试","5. 地毯铺装 → 整平固定","6. 饰品布置 → 挂画/摆件/绿植",
           "7. 整体调整 → 灯光/角度微调","8. 最终验收 → 客户确认"]
    for s in steps:
        msp.add_text(s,height=200,dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=35

    # 3. 验收清单
    y+=30
    msp.add_text("三、竣工验收清单",height=300,
                dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=60

    checks = [
        ("水电",["所有开关插座通电测试","给排水通畅无渗漏","热水器工作正常","马桶冲水正常"]),
        ("泥瓦",["瓷砖无空鼓","地漏排水顺畅","门槛石稳固","窗台石打胶密封"]),
        ("木工",["柜门开关顺畅","抽屉推拉顺滑","吊顶无裂缝","五金件牢固"]),
        ("油漆",["墙面平整无裂纹","阴阳角顺直","踢脚线安装牢固","门套窗套打胶完整"]),
        ("软装",["家具无磕碰划痕","窗帘开合顺畅","灯具全部点亮","饰品摆放到位"]),
        ("设备",["空调制冷/热正常","烟机排烟正常","冰箱运行正常","洗衣机试机正常"]),
    ]

    for cat, items in checks:
        msp.add_text("%s:" % cat,height=220,
                    dxfattribs={"layer":"交付-验收项"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=40
        for item in items:
            msp.add_text("  □ %s" % item,height=180,
                        dxfattribs={"layer":"交付-验收项"}).set_placement((250,y),align=TextEntityAlignment.LEFT); y+=30
        y+=10

    # 4. 质保信息
    y+=20
    msp.add_text("四、质保与服务",height=300,
                dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=60
    warranties=["水电工程质保5年","防水工程质保3年","整体装修质保2年","质保期内免费维修","24小时售后响应"]
    for w in warranties:
        msp.add_text(w,height=200,dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT); y+=35

    y+=30
    msp.add_text("业主签字: ________    日期: ________",height=250,
                dxfattribs={"layer":"交付-交付说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)

    # JSON
    data = {"furniture":furniture_list,"checks":checks,"warranties":warranties}
    json_path = os.path.join(out_dir,"交付方案.json")
    with open(json_path,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)

    return dxf_output_path, json_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../templates/concept_output/交付方案.dxf"
    r,j=generate_delivery_plan(inp,out);print("OK:",r)
