"""设计条件合并器
输入1: 客户填的 Excel 问卷（风格/预算/需求...）
输入2: iPhone RoomPlan JSON（空间尺寸/墙/门窗...）
输出: 统一的设计条件 JSON + DXF 底图
"""
import json, math, os, sys
from collections import OrderedDict
import openpyxl

# ── 导入子模块 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.parse_survey import parse_survey
from modules.roomplan_to_dxf import roomplan_to_dxf


def merge_design_conditions(survey_xlsx, roomplan_json, output_json=None, output_dxf=None):
    """合并问卷 + 扫描数据为统一设计条件"""

    conditions = OrderedDict()

    # 1. 解析问卷（客户主观信息）
    if survey_xlsx and os.path.exists(survey_xlsx):
        survey_data = parse_survey(survey_xlsx)
    else:
        survey_data = {}

    # 2. 解析 RoomPlan（空间客观数据）
    if roomplan_json and os.path.exists(roomplan_json):
        with open(roomplan_json, "r", encoding="utf-8") as f:
            roomplan = json.load(f)

        # 提取空间摘要
        surfaces = roomplan.get("surfaces", [])
        rooms = roomplan.get("rooms", [])

        # 统计
        walls = [s for s in surfaces if s["category"] == "wall"]
        doors = [s for s in surfaces if s["category"] == "door"]
        windows = [s for s in surfaces if s["category"] == "window"]
        beams = [s for s in surfaces if s["category"] == "beam"]
        columns = [s for s in surfaces if s["category"] == "column"]

        # 房间信息
        room_list = []
        total_area = 0
        for rm in rooms:
            dims = rm.get("dimensions", {})
            w = dims.get("x", 0)
            h = dims.get("y", 0)
            area = round(w * h / 1e6, 2)  # mm^2 → m^2
            total_area += area
            room_list.append({
                "name": rm.get("displayName", ""),
                "width_mm": w,
                "height_mm": h,
                "area_m2": area,
                "wall_count": len([s for s in rm.get("surfaces", [])
                                  if s in {wl["identifier"] for wl in walls}]),
            })

        # 总建筑面积估算
        # 用所有房间面积之和（粗略）
        floor_surfaces = [s for s in surfaces if s["category"] == "floor"]
        if floor_surfaces:
            # 用第一个 floor 的尺寸
            pass

        space_data = {
            "source": "iPhone LiDAR (RoomPlan)",
            "total_rooms": len(rooms),
            "total_area_m2": round(total_area, 2),
            "rooms": room_list,
            "wall_count": len(walls),
            "door_count": len(doors),
            "window_count": len(windows),
            "beam_count": len(beams),
            "column_count": len(columns),
            "has_beams": len(beams) > 0,
            "has_columns": len(columns) > 0,
        }

        # 3. 生成 DXF
        if output_dxf:
            roomplan_to_dxf(roomplan_json, output_dxf)
            space_data["dxf_path"] = output_dxf

    else:
        space_data = None

    # 4. 合并
    conditions["project"] = survey_data.get("project", {})
    conditions["family"] = survey_data.get("family", {})
    conditions["style"] = survey_data.get("style", {})
    conditions["rooms_requirements"] = survey_data.get("rooms", {})
    conditions["budget"] = survey_data.get("budget", {})
    conditions["special_requirements"] = survey_data.get("special_requirements", {})
    conditions["space_data"] = space_data  # 空间扫描数据

    # 输出 JSON
    if output_json:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(conditions, f, ensure_ascii=False, indent=2)
        return conditions, output_json, space_data.get("dxf_path") if space_data else None

    return conditions, None, None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="合并问卷 + 扫描数据为统一设计条件")
    parser.add_argument("--xlsx", default=None, help="设计需求问卷.xlsx")
    parser.add_argument("--scan", default="templates/sample_roomplan.json", help="RoomPlan JSON")
    parser.add_argument("--output", default="templates/设计条件.json", help="输出 JSON")
    parser.add_argument("--dxf", default="templates/原始结构底图.dxf", help="输出 DXF")
    args = parser.parse_args()

    result, json_path, dxf_path = merge_design_conditions(
        args.xlsx, args.scan, args.output, args.dxf
    )

    print("=== 设计条件合并完成 ===")
    print("JSON:", json_path)
    print("DXF:", dxf_path)
    print()

    # 打印摘要
    sd = result.get("space_data", {})
    print("空间数据:")
    print("  来源:", sd.get("source", "N/A"))
    print("  房间: %d 个" % sd.get("total_rooms", 0))
    print("  总面积: %.1f m2" % sd.get("total_area_m2", 0))
    print("  墙体: %d 面" % sd.get("wall_count", 0))
    print("  门: %d 个" % sd.get("door_count", 0))
    print("  窗: %d 个" % sd.get("window_count", 0))
    print("  梁: %d 个" % sd.get("beam_count", 0))
    print("  柱: %d 个" % sd.get("column_count", 0))
    print()
    if sd.get("rooms"):
        print("房间明细:")
        for rm in sd["rooms"]:
            print("  %s: %d×%dmm (%.1f m2)" % (
                rm["name"], rm["width_mm"], rm["height_mm"], rm["area_m2"]))


if __name__ == "__main__":
    main()
