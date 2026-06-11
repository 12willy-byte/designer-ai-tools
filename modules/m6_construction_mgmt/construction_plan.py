"""M6: 施工跟进与项目管理
自动生成施工计划、阶段验收节点、施工日志
"""
import json, os, sys, math
from collections import OrderedDict
import ezdxf
from ezdxf.enums import TextEntityAlignment
from datetime import datetime, timedelta


def generate_construction_plan(conditions_json_path, dxf_output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    project = conditions.get("project", {})
    space = conditions.get("space_data", {})
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")

    total_area = space.get("total_area_m2", 0)

    # ── 工期计算 (按面积估算) ──
    # 标准工期: 100m² 约 60天，按比例调整
    base_days = max(30, int(total_area / 100 * 60))
    start_date = datetime.now()

    phases = [
        ("办理入场手续",      2,  "物业报备、交押金、保护公共区域"),
        ("拆改阶段",          max(3, int(total_area * 0.05)),
                              "墙体拆除、垃圾清运、新建墙体"),
        ("水电改造",          max(5, int(total_area * 0.08)),
                              "开槽布管、强弱电布线、给排水安装"),
        ("防水工程",          3,  "卫生间/厨房防水、闭水试验48h"),
        ("泥瓦工程",          max(7, int(total_area * 0.1)),
                              "瓷砖铺贴、门槛石、窗台石安装"),
        ("木工/吊顶",         max(5, int(total_area * 0.08)),
                              "吊顶安装、背景墙基层、定制柜安装"),
        ("油漆工程",          max(7, int(total_area * 0.08)),
                              "墙面批灰打磨、底漆面漆、壁纸铺贴"),
        ("安装阶段",          max(5, int(total_area * 0.06)),
                              "灯具/开关/洁具/橱柜/门安装"),
        ("软装进场",          3,  "家具/窗帘/装饰品摆放"),
        ("竣工验收",          1,  "全房验收、问题整改、交付"),
    ]

    # ── 计算每个阶段的实际日期 ──
    schedule = []
    current_date = start_date
    for name, days, desc in phases:
        if days < 1: days = 1
        end_date = current_date + timedelta(days=days)
        schedule.append({
            "phase": name,
            "days": days,
            "start": current_date.strftime("%m/%d"),
            "end": end_date.strftime("%m/%d"),
            "description": desc,
            "checklist": generate_checklist(name),
        })
        current_date = end_date + timedelta(days=1)  # 间隔1天

    total_days = (current_date - start_date).days
    estimated_end = start_date + timedelta(days=total_days)

    # ── 生成 DXF ──
    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    for ln, c, lw in [("施工-进度计划", 6, 35), ("施工-节点验收", 2, 20),
                      ("施工-检查项", 3, 9), ("施工-施工说明", 8, 9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color": c, "lineweight": lw})

    y = 200
    msp.add_text("=== 施工进度计划 ===", height=400,
                dxfattribs={"layer": "施工-施工说明"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 80

    msp.add_text("项目: %s    面积: %.1f m2    工期: %d 天" % (
        project.get("name","未命名"), total_area, total_days),
        height=250, dxfattribs={"layer": "施工-施工说明"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 60
    msp.add_text("计划开工: %s    计划竣工: %s" % (
        start_date.strftime("%Y-%m-%d"), estimated_end.strftime("%Y-%m-%d")),
        height=220, dxfattribs={"layer": "施工-施工说明"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 80

    for s in schedule:
        # 进度条
        bar_w = int(s["days"] / total_days * 400)
        bar_color = 2  # 黄色
        msp.add_solid_face(
            [(200, y), (200+bar_w, y), (200+bar_w, y+15), (200, y+15)],
            dxfattribs={"layer": "施工-进度计划"}
        )

        msp.add_text("%s (%d天) %s-%s" % (s["phase"], s["days"], s["start"], s["end"]),
                    height=200, dxfattribs={"layer": "施工-进度计划"}).set_placement(
                        (220, y+20), align=TextEntityAlignment.LEFT)
        y += 45

    # 节点验收
    y += 40
    msp.add_text("=== 节点验收清单 ===", height=350,
                dxfattribs={"layer": "施工-施工说明"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 70

    for s in schedule:
        msp.add_text("▸ %s  (%s-%s)" % (s["phase"], s["start"], s["end"]),
                    height=220, dxfattribs={"layer": "施工-节点验收"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
        y += 40
        for item in s["checklist"][:5]:
            msp.add_text("  □ %s" % item, height=170,
                        dxfattribs={"layer": "施工-检查项"}).set_placement((230, y), align=TextEntityAlignment.LEFT)
            y += 30

    # 保存
    doc.saveas(dxf_output_path)

    # 保存 JSON
    schedule_data = {
        "project": project.get("name","未命名"),
        "total_area_m2": total_area,
        "total_days": total_days,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": estimated_end.strftime("%Y-%m-%d"),
        "phases": schedule,
    }
    json_path = os.path.join(out_dir, "施工计划.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(schedule_data, f, ensure_ascii=False, indent=2)

    print("工期: %d 天 (%s → %s)" % (total_days,
          start_date.strftime("%Y-%m-%d"), estimated_end.strftime("%Y-%m-%d")))
    return dxf_output_path, json_path


def generate_checklist(phase):
    """每个阶段的验收检查项"""
    checklists = {
        "办理入场手续": ["物业手续已办妥", "施工许可已张贴", "公共区域已保护", "临时水电已接通", "材料堆放区已划定"],
        "拆改阶段": ["拆墙位置与图纸一致", "承重结构未破坏", "垃圾已清运完毕", "新砌墙体位置准确", "拉结筋已植入"],
        "水电改造": ["开槽深度达标", "线管固定牢固", "强弱电间距>300mm", "水管打压测试通过", "回路划分合理"],
        "防水工程": ["基层处理平整", "涂刷厚度达标", "墙角圆弧处理", "闭水试验48h无渗漏", "保护层已施工"],
        "泥瓦工程": ["地面平整度≤3mm", "瓷砖留缝均匀", "空鼓率≤5%", "排水坡度正确", "门槛石已安装"],
        "木工/吊顶": ["龙骨间距符合标准", "石膏板接缝处理", "灯位预留准确", "空调风口预留", "柜体水平垂直"],
        "油漆工程": ["墙面平整无裂缝", "阴阳角顺直", "底漆已涂刷", "面漆均匀无色差", "成品保护到位"],
        "安装阶段": ["灯具安装牢固", "开关插座接线正确", "洁具防水打胶", "门安装垂直", "橱柜门板调整"],
        "软装进场": ["家具无磕碰", "窗帘挂装整齐", "地毯铺平整", "饰品摆放到位", "绿植已到位"],
        "竣工验收": ["全房保洁完成", "所有功能测试通过", "问题清单已记录", "业主确认签字", "质保卡已交付"],
    }
    return checklists.get(phase, ["验收合格"])


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "../templates/concept_output/施工计划.dxf"
    r, j = generate_construction_plan(inp, out)
    print("DXF:", r)
    print("JSON:", j)
