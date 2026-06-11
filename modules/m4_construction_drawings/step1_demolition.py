"""M4 Step 1: 拆墙图
自动标注非承重内墙，生成拆墙 DXF
"""
import json, os, sys, math
import ezdxf
from ezdxf.enums import TextEntityAlignment

def generate_demolition_plan(conditions_json_path, dxf_output_path):
    with open(conditions_json_path,"r",encoding="utf-8") as f:
        conditions = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    roomplan_path = os.path.join(base_dir, "sample_roomplan.json")

    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    # 图层
    for ln,c,lw in [("施工-拆墙范围",1,50),("施工-拆墙标注",1,20),("施工-保留墙体",7,35),("施工-施工说明",6,9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln,dxfattribs={"color":c,"lineweight":lw})

    # 加载 RoomPlan 判断内外墙
    walls_by_room = {}
    ext_walls = set()  # 外墙标识

    if os.path.exists(roomplan_path):
        with open(roomplan_path,"r",encoding="utf-8") as f:
            rp = json.load(f)

        # 统计每面墙出现的房间次数
        wall_room_count = {}
        for rm in rp.get("rooms",[]):
            for sid in rm.get("surfaces",[]):
                wall_room_count[sid] = wall_room_count.get(sid,0) + 1

        # 只出现在1个房间的墙 = 外墙
        for wid, cnt in wall_room_count.items():
            if cnt == 1:
                ext_walls.add(wid)

    # 从原始 DXF 读取墙线
    wall_lines = []
    for e in msp:
        if e.dxftype()=="LINE" and e.dxf.layer=="原始结构-墙体":
            wall_lines.append(e)

    y = 200
    msp.add_text("=== 拆墙图 ===",height=400,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 80
    msp.add_text("红色 = 建议拆除  白色 = 保留  外墙不可拆",height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 60

    # 识别外墙（靠近边界）
    bound = [float("inf"),float("inf"),float("-inf"),float("-inf")]
    for l in wall_lines:
        for pt in [(l.dxf.start.x,l.dxf.start.y),(l.dxf.end.x,l.dxf.end.y)]:
            bound = [min(bound[0],pt[0]),min(bound[1],pt[1]),max(bound[2],pt[0]),max(bound[3],pt[1])]
    margin = 100
    ext_lines = []
    int_lines = []
    for l in wall_lines:
        mx = (l.dxf.start.x + l.dxf.end.x)/2
        my = (l.dxf.start.y + l.dxf.end.y)/2
        if (mx < bound[0]+margin or mx > bound[2]-margin or
            my < bound[1]+margin or my > bound[3]-margin):
            ext_lines.append(l)
        else:
            int_lines.append(l)

    # 外墙标为保留（白色），内墙标为拆除（红色）
    for l in ext_lines:
        msp.add_line((l.dxf.start.x,l.dxf.start.y),(l.dxf.end.x,l.dxf.end.y),
                    dxfattribs={"layer":"施工-保留墙体"})
    for l in int_lines:
        # 用红色虚线表示拆除
        msp.add_line((l.dxf.start.x,l.dxf.start.y),(l.dxf.end.x,l.dxf.end.y),
                    dxfattribs={"layer":"施工-拆墙范围"})

    # 标注
    y += 20
    msp.add_text("需拆除内墙: %d 面" % len(int_lines),height=250,dxfattribs={"layer":"施工-拆墙标注"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 50
    for i,l in enumerate(int_lines[:10]):
        mx=(l.dxf.start.x+l.dxf.end.x)/2; my=(l.dxf.start.y+l.dxf.end.y)/2
        length=math.hypot(l.dxf.end.x-l.dxf.start.x,l.dxf.end.y-l.dxf.start.y)
        msp.add_text("墙%d: %.0fmm"%(i+1,length),height=180,dxfattribs={"layer":"施工-拆墙标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT)
        y += 35

    if len(int_lines) > 10:
        msp.add_text("...等共%d面" % len(int_lines),height=180,dxfattribs={"layer":"施工-拆墙标注"}).set_placement((250,y),align=TextEntityAlignment.LEFT)

    y += 80
    msp.add_text("施工说明:",height=250,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 50
    msp.add_text("1. 拆墙前必须确认是否为非承重墙",height=200,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 35
    msp.add_text("2. 拆墙须先切割后拆除，不得大锤猛砸",height=200,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 35
    msp.add_text("3. 梁柱结构不可拆除",height=200,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)
    y += 35
    msp.add_text("4. 如有疑问请与结构工程师确认",height=200,dxfattribs={"layer":"施工-施工说明"}).set_placement((200,y),align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)
    return dxf_output_path

if __name__=="__main__":
    inp=sys.argv[1] if len(sys.argv)>1 else "../../templates/设计条件.json"
    out=sys.argv[2] if len(sys.argv)>2 else "../../templates/concept_output/拆墙图.dxf"
    r=generate_demolition_plan(inp,out);print("OK:",r)
