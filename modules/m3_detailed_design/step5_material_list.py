"""M3 Step 5: 材料清单自动算量
从 RoomPlan 数据自动计算各材料用量
"""
import json, os, sys, math
from collections import OrderedDict
import ezdxf
from ezdxf.enums import TextEntityAlignment

def calculate_materials(conditions_json_path, dxf_output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    space = conditions.get("space_data", {})
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")

    # 从 M2 材质方案读取材质选型
    mat_data = {}
    mat_img_path = os.path.join(out_dir, "材质方案.png")
    # 简单读取条件中的材质偏好
    style = conditions.get("style", {})

    rows = []
    total_cost = 0

    for rm in space.get("rooms", []):
        w = rm["width_mm"] / 1000  # m
        h = rm["height_mm"] / 1000  # m
        area_floor = w * h
        perimeter = 2 * (w + h)
        area_wall = perimeter * 2.8  # 墙高 2.8m
        # 减去门窗面积（估算）
        door_area = 0.9 * 2.1  # 标准门
        window_area = 2.4 * 1.5  # 标准窗
        area_wall -= (door_area + window_area)

        rows.append(OrderedDict([
            ("空间", rm["name"]),
            ("面积_m2", round(area_floor, 1)),
            ("周长_m", round(perimeter, 1)),
            ("墙面_m2", round(area_wall, 1)),
            ("地面材料", style.get("floor_material", "木地板")),
            ("地面_含损耗", round(area_floor * 1.05, 1)),
        ]))

        # 估算费用
        price_per_m2 = {"木地板": 200, "瓷砖": 150, "微水泥": 300, "石材": 500}
        mat_name = style.get("floor_material", "木地板")
        for k, v in price_per_m2.items():
            if k in mat_name:
                total_cost += area_floor * v
                break

    # 总汇总
    total_floor = sum(r["面积_m2"] for r in rows)
    total_wall = sum(r["墙面_m2"] for r in rows)

    # 输出到 DXF
    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    for ln, c, lw in [("深化-材料清单", 6, 20), ("深化-材料标注", 2, 9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color": c, "lineweight": lw})

    y = 200
    msp.add_text("=== 材料用量清单 ===", height=350,
                dxfattribs={"layer": "深化-材料清单"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 80

    # 表头
    headers = ["空间", "面积(m2)", "周长(m)", "墙面(m2)", "地面材料", "含损耗(m2)"]
    header_text = "  ".join("%-12s" % h for h in headers)
    msp.add_text(header_text, height=200,
                dxfattribs={"layer": "深化-材料清单"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 50

    for r in rows:
        line = "  ".join("%-12s" % str(r.get(h[0], "")) for h in zip(headers))
        msp.add_text(line, height=180,
                    dxfattribs={"layer": "深化-材料标注"}).set_placement((220, y), align=TextEntityAlignment.LEFT)
        y += 40

    y += 50
    msp.add_text("合计: 地面 %.1f m2  墙面 %.1f m2" % (total_floor, total_wall),
                height=220, dxfattribs={"layer": "深化-材料清单"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 40
    if total_cost:
        msp.add_text("地面材料预估费用: %.0f 元（仅供参考，以实际采购为准）" % total_cost,
                    height=200, dxfattribs={"layer": "深化-材料标注"}).set_placement((200, y), align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)

    # 同时输出 JSON
    json_path = os.path.join(out_dir, "材料清单.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"rooms": rows, "total_floor_m2": total_floor, "total_wall_m2": total_wall,
                   "estimated_floor_cost": total_cost}, f, ensure_ascii=False, indent=2)

    return dxf_output_path, json_path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "../templates/concept_output/材料清单.dxf"
    r, j = calculate_materials(inp, out)
    print("DXF:", r)
    print("JSON:", j)
