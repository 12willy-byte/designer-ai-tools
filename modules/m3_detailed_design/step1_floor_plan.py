"""M3 Step 1: 平面布置图生成器
基于 RoomPlan 底图 + 布局建议 → 精确的 DXF 平面布置图
"""
import json, os, sys, math, re
from openai import OpenAI
import ezdxf
from ezdxf.enums import TextEntityAlignment
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# ── 标准家具尺寸库（mm） ──
FURNITURE_LIB = {
    "L型沙发":        {"width": 2800, "depth": 1800, "color": 5},
    "三人沙发":       {"width": 2200, "depth": 900,  "color": 5},
    "双人沙发":       {"width": 1600, "depth": 850,  "color": 5},
    "单人沙发":       {"width": 900,  "depth": 850,  "color": 5},
    "茶几":           {"width": 1200, "depth": 600,  "color": 4},
    "电视柜":         {"width": 2400, "depth": 400,  "color": 4},
    "餐桌":           {"width": 1400, "depth": 800,  "color": 3},
    "餐椅":           {"width": 500,  "depth": 500,  "color": 3},
    "双人床":         {"width": 1800, "depth": 2000, "color": 2},
    "单人床":         {"width": 1200, "depth": 2000, "color": 2},
    "床头柜":         {"width": 450,  "depth": 450,  "color": 2},
    "衣柜":           {"width": 1800, "depth": 600,  "color": 6},
    "书桌":           {"width": 1200, "depth": 600,  "color": 4},
    "书椅":           {"width": 500,  "depth": 500,  "color": 4},
    "书架":           {"width": 900,  "depth": 350,  "color": 6},
    "洗手台":         {"width": 600,  "depth": 500,  "color": 3},
    "马桶":           {"width": 400,  "depth": 700,  "color": 2},
    "淋浴房":         {"width": 900,  "depth": 900,  "color": 5},
    "浴缸":           {"width": 1500, "depth": 750,  "color": 5},
    "冰箱":           {"width": 800,  "depth": 700,  "color": 4},
    "烟机灶具":       {"width": 800,  "depth": 500,  "color": 4},
    "水槽":           {"width": 800,  "depth": 450,  "color": 4},
    "洗衣机":         {"width": 600,  "depth": 600,  "color": 4},
    "烘干机":         {"width": 600,  "depth": 600,  "color": 4},
}

SYSTEM_PROMPT = """你是资深室内设计师，负责为每个房间生成精确的家具布置方案。

输入每个房间的尺寸（毫米）、门窗位置、客户需求。
请为每个房间输出家具布置建议，格式如下：

客厅:
- 三人沙发: 靠西墙, 距北墙500
- 茶几: 沙发前方正中, 距沙发400
- 电视柜: 东墙, 整面墙, 深度400
- 边几: 沙发右侧

主卧:
- 双人床: 靠北墙居中
- 床头柜x2: 床两侧
- 衣柜: 南墙, 整面墙1800宽

要求：
- 家具尺寸参考标准尺寸（我会根据类别匹配）
- 位置用"靠X墙, 距Y墙XXX"描述
- 每个空间输出 3-8 件家具
- 只输出房间名和家具列表，不要多余文字
"""


def identify_walls(room_name, room_data, roomplan_data):
    """基于 RoomPlan 数据分析房间墙的方位（简化版）"""
    # 从原始数据中找该房间的墙
    surfaces = roomplan_data.get("surfaces", [])
    rooms = roomplan_data.get("rooms", [])

    # 获取该房间的墙列表
    for rm in rooms:
        if rm.get("displayName") == room_name:
            wall_ids = [s for s in rm.get("surfaces", [])]
            walls = []
            for sid in wall_ids:
                for s in surfaces:
                    if s["identifier"] == sid and s["category"] == "wall":
                        walls.append(s)
            return walls
    return []


def generate_floor_plan_dxf(conditions_json_path, dxf_output_path):
    """生成详细的平面布置图 DXF"""
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    # 加载 RoomPlan 原始数据
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    roomplan_path = os.path.join(base_dir, "sample_roomplan.json")
    roomplan_data = {}
    if os.path.exists(roomplan_path):
        with open(roomplan_path, "r", encoding="utf-8") as f:
            roomplan_data = json.load(f)

    space = conditions.get("space_data", {})
    rooms_req = conditions.get("rooms_requirements", {})
    style = conditions.get("style", {})

    # 加载原始底图 DXF
    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    if os.path.exists(orig_dxf):
        doc = ezdxf.readfile(orig_dxf)
    else:
        doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # ── 新增深化图层 ──
    LAYERS = OrderedDict([
        ("深化-墙体填充",    {"c": 9,  "lw": 9}),
        ("深化-家具布置",    {"c": 5,  "lw": 35}),
        ("深化-家具标注",    {"c": 5,  "lw": 9}),
        ("深化-尺寸标注",    {"c": 2,  "lw": 9}),
        ("深化-房间标号",    {"c": 6,  "lw": 9}),
        ("深化-铺装分区",    {"c": 8,  "lw": 9}),
        ("深化-标高",        {"c": 3,  "lw": 9}),
    ])
    for ln, lp in LAYERS.items():
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color": lp["c"], "lineweight": lp["lw"]})

    # ── 调用 DeepSeek 生成家具布局 ──
    prompt = "请为以下户型生成详细的家具布置方案：\n\n"
    if space.get("rooms"):
        for rm in space["rooms"]:
            prompt += "\n【%s】 %d×%dmm (%.1f m2)\n" % (
                rm["name"], rm["width_mm"], rm["height_mm"], rm["area_m2"])
            req = rooms_req.get(rm["name"], {})
            for k, v in req.items():
                if v: prompt += "  %s: %s\n" % (k, v)

    prompt += "\n风格: %s\n" % style.get("primary_style","现代简约")

    sys_prompt = "你是室内设计师，请为每个房间列出家具清单（只输出房间名和家具列表）。\n格式：\n客厅:\n- 三人沙发: 靠西墙, 距北墙500\n- 茶几: 沙发前方\n..."

    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role":"system","content":sys_prompt},
                  {"role":"user","content":prompt}],
        temperature=0.5,
        max_tokens=2000,
    )

    layout_text = resp.choices[0].message.content

    # ── 解析家具布局并绘制 ──
    current_room = None
    furniture_placed = []
    y_text = 200

    for line in layout_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 检查是否房间名
        if ":" not in line and ("厅" in line or "室" in line or "房" in line or "间" in line):
            current_room = line.replace(":", "").strip()
            # 写房间标题到 DXF
            msp.add_text("【%s】" % current_room, height=350,
                        dxfattribs={"layer":"深化-房间标号"}).set_placement(
                            (200, y_text), align=TextEntityAlignment.LEFT)
            y_text += 60
            continue

        if ":" in line and current_room:
            parts = line.split(":", 1)
            if len(parts) == 2:
                f_name = parts[0].strip().lstrip("- ").lstrip("* ")
                f_desc = parts[1].strip()
                # 匹配标准家具库
                matched_size = None
                matched_key = None
                for k, v in FURNITURE_LIB.items():
                    if k in f_name or f_name in k:
                        matched_size = v
                        matched_key = k
                        break

                if matched_size:
                    w, d = matched_size["width"], matched_size["depth"]
                    # 绘制家具矩形
                    x_pos = 500
                    y_pos = y_text

                    # 画矩形
                    msp.add_lwpolyline([
                        (x_pos, y_pos),
                        (x_pos + w/10, y_pos),
                        (x_pos + w/10, y_pos + d/10),
                        (x_pos, y_pos + d/10)
                    ], close=True, dxfattribs={"layer":"深化-家具布置"})

                    # 家具名
                    label = "%s %d×%d" % (matched_key, w, d)
                    msp.add_text(label, height=150,
                                dxfattribs={"layer":"深化-家具标注"}).set_placement(
                                    (x_pos + w/20 + 50, y_pos + d/20 - 30),
                                    align=TextEntityAlignment.LEFT)

                    furniture_placed.append((current_room, matched_key, f_desc))
                    y_text += d/10 + 150
                else:
                    # 无法匹配的用文字描述
                    msp.add_text("  %s: %s" % (f_name, f_desc[:40]), height=150,
                                dxfattribs={"layer":"深化-家具标注"}).set_placement(
                                    (500, y_text), align=TextEntityAlignment.LEFT)
                    y_text += 40

    # ── 为每个房间添加尺寸标注 ──
    if space.get("rooms"):
        y_dim = y_text + 100
        for rm in space["rooms"]:
            msp.add_text("%s: %d × %d mm  (%.1f m2)" % (
                rm["name"], rm["width_mm"], rm["height_mm"], rm["area_m2"]),
                height=180, dxfattribs={"layer":"深化-尺寸标注"}).set_placement(
                    (200, y_dim), align=TextEntityAlignment.LEFT)
            y_dim += 40

    # ── 写入布局建议文本（供设计师参考） ──
    y_note = y_dim + 80
    msp.add_text("=== 家具布置说明 ===", height=250,
                dxfattribs={"layer":"深化-家具标注"}).set_placement(
                    (200, y_note), align=TextEntityAlignment.LEFT)
    y_note += 50

    for room, f_name, desc in furniture_placed:
        msp.add_text("%s - %s: %s" % (room, f_name, desc[:50]), height=150,
                    dxfattribs={"layer":"深化-家具标注"}).set_placement(
                        (250, y_note), align=TextEntityAlignment.LEFT)
        y_note += 35

    doc.saveas(dxf_output_path)
    return dxf_output_path


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "../templates/concept_output/平面布置图.dxf"
    os.makedirs(os.path.dirname(out), exist_ok=True)

    r = generate_floor_plan_dxf(inp, out)
    sz = os.path.getsize(out)
    print("OK: %s (%d bytes)" % (r, sz))


if __name__ == "__main__":
    main()
