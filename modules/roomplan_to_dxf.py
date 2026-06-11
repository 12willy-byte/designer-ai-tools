"""RoomPlan JSON -> DXF 转换器 v2
支持：多房间、梁柱管道、自动标注、CAD 可编辑图层
"""
import json, math, os, sys
from collections import OrderedDict, defaultdict
import ezdxf
from ezdxf.enums import TextEntityAlignment

# ACI 颜色
C = {"WALL":7, "FILL":8, "DOOR":5, "WINDOW":3, "DIM":2, "TEXT":6,
     "BEAM":6, "COLUMN":6, "PIPE":4, "GRID":9, "ROOM":5}

def tform(m, x, y, z):
    return (m[0]*x+m[4]*y+m[8]*z+m[12], m[1]*x+m[5]*y+m[9]*z+m[13],
            m[2]*x+m[6]*y+m[10]*z+m[14])

def wall_ends(m, l):
    a = tform(m, 0,0,0)
    b = tform(m, l,0,0)
    return (round(a[0],1), round(a[2],1)), (round(b[0],1), round(b[2],1))


def roomplan_to_dxf(json_path, dxf_path):
    with open(json_path,"r",encoding="utf-8") as f:
        data = json.load(f)

    surfaces = data.get("surfaces",[])
    smap = {s["identifier"]:s for s in surfaces}
    walls = [s for s in surfaces if s["category"]=="wall"]
    doors = [s for s in surfaces if s["category"]=="door"]
    windows = [s for s in surfaces if s["category"]=="window"]
    beams = [s for s in surfaces if s["category"]=="beam"]
    columns = [s for s in surfaces if s["category"]=="column"]

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    LAYERS = OrderedDict([
        ("原始结构-墙体",     {"c":C["WALL"],  "lw":50}),
        ("原始结构-墙填充",   {"c":C["FILL"],  "lw":9}),
        ("原始结构-门",       {"c":C["DOOR"],  "lw":35}),
        ("原始结构-窗",       {"c":C["WINDOW"],"lw":35}),
        ("原始结构-梁",       {"c":C["BEAM"],  "lw":50}),
        ("原始结构-柱",       {"c":C["COLUMN"],"lw":50}),
        ("原始结构-管道",     {"c":C["PIPE"],  "lw":35}),
        ("原始结构-尺寸标注", {"c":C["DIM"],   "lw":9}),
        ("原始结构-房间标号", {"c":C["ROOM"],  "lw":9}),
        ("原始结构-辅助线",   {"c":C["GRID"],  "lw":9}),
    ])
    for n,p in LAYERS.items():
        doc.layers.add(n, dxfattribs={"color":p["c"],"lineweight":p["lw"]})

    # 1. 绘制墙体
    wall_data = []  # (id, start_xy, end_xy, wall_len)
    for w in walls:
        start, end = wall_ends(w["transform"], w["dimensions"]["x"])
        l = math.hypot(end[0]-start[0], end[1]-start[1])
        wall_data.append((w["identifier"], start, end, l))

        wt = 120
        dx = end[0]-start[0]; dy = end[1]-start[1]
        if l<1: continue
        nx = -dy/l*wt/2; ny = dx/l*wt/2
        p1=(start[0]+nx,start[1]+ny); p2=(end[0]+nx,end[1]+ny)
        p3=(start[0]-nx,start[1]-ny); p4=(end[0]-nx,end[1]-ny)

        msp.add_line(p1,p2,dxfattribs={"layer":"原始结构-墙体"})
        msp.add_line(p3,p4,dxfattribs={"layer":"原始结构-墙体"})
        msp.add_line(p1,p3,dxfattribs={"layer":"原始结构-墙体"})
        msp.add_line(p2,p4,dxfattribs={"layer":"原始结构-墙体"})
        msp.add_lwpolyline([p1,p2,p4,p3],close=True,
                           dxfattribs={"layer":"原始结构-墙填充"})

    wall_map = {w[0]:(w[1],w[2],w[3]) for w in wall_data}

    # 2. 门/窗
    openings = []  # (wall_id, pos, width, typ)
    for objs, typ in [(doors,"door"),(windows,"window")]:
        for o in objs:
            pid = o.get("parentIdentifier")
            if pid not in wall_map: continue
            origin, end, wl = wall_map[pid]
            vec = (end[0]-origin[0], end[1]-origin[1])
            pos = tform(o["transform"],0,0,0)
            if wl>0:
                dist = ((pos[0]-origin[0])*vec[0]+(pos[2]-origin[1])*vec[1])/wl
                openings.append((pid, dist, o["dimensions"]["x"], typ))

    for w in walls:
        wid = w["identifier"]
        ops = sorted([o for o in openings if o[0]==wid], key=lambda x:x[1])
        if not ops: continue
        start, end, wl = wall_map[wid]
        dx=end[0]-start[0]; dy=end[1]-start[1]
        if wl<1: continue
        wt=120
        nx=-dy/wl*wt/2; ny=dx/wl*wt/2

        for _pid, pos, width, typ in ops:
            t1=pos/w["dimensions"]["x"]; t2=(pos+width)/w["dimensions"]["x"]
            ax=start[0]+dx*t1; ay=start[1]+dy*t1
            bx=start[0]+dx*t2; by=start[1]+dy*t2

            if typ=="door":
                cx,cy=ax-nx,ay-ny
                fnx=-dy/wl; fny=dx/wl
                sa=math.degrees(math.atan2(-fnx,fny))
                msp.add_arc((cx,cy),width,sa,sa+90,
                           dxfattribs={"layer":"原始结构-门"})
                msp.add_line((cx,cy),(cx+width*fnx,cy+width*fny),
                            dxfattribs={"layer":"原始结构-门"})
            else:
                p1=(ax+nx,ay+ny);p2=(bx+nx,by+ny)
                p3=(ax-nx,ay-ny);p4=(bx-nx,by-ny)
                msp.add_line(p1,p2,dxfattribs={"layer":"原始结构-窗"})
                msp.add_line(p3,p4,dxfattribs={"layer":"原始结构-窗"})
                mx=(p1[0]+p3[0])/2;my=(p1[1]+p3[1])/2
                msp.add_line((mx,my),((p2[0]+p4[0])/2,(p2[1]+p4[1])/2),
                            dxfattribs={"layer":"原始结构-窗"})

    # 3. 梁/柱
    for b in beams:
        pos = tform(b["transform"],0,0,0)
        w=b["dimensions"]["x"]; h=b["dimensions"].get("y",w)
        msp.add_lwpolyline([(pos[0]-w/2,pos[2]-h/2),
                           (pos[0]+w/2,pos[2]-h/2),
                           (pos[0]+w/2,pos[2]+h/2),
                           (pos[0]-w/2,pos[2]+h/2)],close=True,
                           dxfattribs={"layer":"原始结构-梁"})
        if w>500 or h>500:
            msp.add_text("梁 %dx%d"%(int(w),int(h)),height=150,
                        dxfattribs={"layer":"原始结构-梁"}).set_placement(
                            (pos[0],pos[2]),align=TextEntityAlignment.CENTER)

    for c in columns:
        pos = tform(c["transform"],0,0,0)
        s=c["dimensions"]["x"]
        msp.add_circle((pos[0],pos[2]),s/2,
                      dxfattribs={"layer":"原始结构-柱"})

    # 4. 尺寸标注
    for w in walls:
        wid = w["identifier"]
        if wid not in wall_map: continue
        start,end,wl = wall_map[wid]
        dx=end[0]-start[0]; dy=end[1]-start[1]
        if wl<1: continue
        off=500; ox=-dy/wl*off; oy=dx/wl*off
        pd1=(start[0]+ox,start[1]+oy); pd2=(end[0]+ox,end[1]+oy)

        msp.add_line(start,pd1,dxfattribs={"layer":"原始结构-尺寸标注"})
        msp.add_line(end,pd2,dxfattribs={"layer":"原始结构-尺寸标注"})
        msp.add_line(pd1,pd2,dxfattribs={"layer":"原始结构-尺寸标注"})

        arr=100
        msp.add_line((pd1[0]-arr*oy/off,pd1[1]+arr*ox/off),
                     (pd1[0]+arr*oy/off,pd1[1]-arr*ox/off),
                     dxfattribs={"layer":"原始结构-尺寸标注"})
        msp.add_line((pd2[0]-arr*oy/off,pd2[1]+arr*ox/off),
                     (pd2[0]+arr*oy/off,pd2[1]-arr*ox/off),
                     dxfattribs={"layer":"原始结构-尺寸标注"})

        mx=(pd1[0]+pd2[0])/2; my=(pd1[1]+pd2[1])/2
        msp.add_text("%d"%(int(wl)),
                     height=180,dxfattribs={"layer":"原始结构-尺寸标注"}
                    ).set_placement((mx,my+60),align=TextEntityAlignment.CENTER)

    # 5. 房间标号
    rooms = data.get("rooms",[])
    for ri, rm in enumerate(rooms, 1):
        name = rm.get("displayName","")
        if not name: continue
        pts = []
        for sid in rm.get("surfaces",[]):
            if sid in wall_map:
                s,e,_ = wall_map[sid]
                pts.append(((s[0]+e[0])/2,(s[1]+e[1])/2))
        if pts:
            cx = sum(p[0] for p in pts)/len(pts)
            cy = sum(p[1] for p in pts)/len(pts)
        else:
            cx,cy = 0,0

        r = 400
        msp.add_circle((cx,cy),r,dxfattribs={"layer":"原始结构-房间标号"})
        msp.add_text("%d"%ri,height=300,
                    dxfattribs={"layer":"原始结构-房间标号"}
                    ).set_placement((cx,cy-150),align=TextEntityAlignment.CENTER)

        dims = rm.get("dimensions",{})
        label = "%s" % name
        if dims.get("x") and dims.get("y"):
            label = "%s (%d×%d)" % (name, dims["x"], dims["y"])
        msp.add_text(label,height=200,dxfattribs={"layer":"原始结构-房间标号"}
                    ).set_placement((cx+r+200,cy),align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_path)
    return dxf_path


if __name__=="__main__":
    inp = sys.argv[1] if len(sys.argv)>1 else "templates/sample_roomplan.json"
    out = sys.argv[2] if len(sys.argv)>2 else "templates/原始结构底图.dxf"
    if not os.path.exists(inp):
        print("File not found:",inp); sys.exit(1)
    r = roomplan_to_dxf(inp,out)
    sz = os.path.getsize(out)
    print("OK: %s (%d bytes)"%(r,sz))
