"""
施工验收清单 & 进度计划生成器 v2
从 Scene3D 数据推导工期、定制验收项
项目唯一数据源: Scene3D
"""
from datetime import datetime, timedelta
from core.scene3d import Scene3D


def generate_acceptance_checklist(scene: Scene3D = None) -> list[dict]:
    """生成竣工验收清单，可根据场景定制"""
    checks = [
        {"category": "水电", "items": [
            "所有开关插座通电测试", "给排水通畅无渗漏",
            "热水器工作正常", "马桶冲水正常",
            "地漏排水顺畅", "强弱电箱标识清晰",
        ]},
        {"category": "泥瓦", "items": [
            "瓷砖无空鼓（敲击检查）", "地面找平误差<3mm",
            "门槛石稳固无松动", "窗台石打胶密封",
            "瓷砖缝隙均匀（美缝完成）",
        ]},
        {"category": "木工", "items": [
            "柜门开关顺畅无卡顿", "抽屉推拉顺滑",
            "吊顶无裂缝无变形", "五金件安装牢固",
            "门套窗套打胶完整",
        ]},
        {"category": "油漆", "items": [
            "墙面平整无裂纹", "阴阳角顺直",
            "踢脚线安装牢固", "漆面无流挂/起泡",
            "颜色均匀无色差",
        ]},
        {"category": "设备", "items": [
            "空调制冷/制热正常", "烟机排烟正常",
            "冰箱运行正常", "洗衣机试机正常",
            "新风系统运行正常",
        ]},
    ]

    # 如果有场景数据，根据房间数定制
    if scene and isinstance(scene, Scene3D):
        room_names = [r.name for r in scene.rooms.values()]
        if "厨房" in "".join(room_names):
            checks.append({"category": "厨房专项", "items": [
                "橱柜门板平整无变形", "台面接缝处理完好",
                "水槽下水无渗漏", "烟道止逆阀安装正确",
            ]})
        if any("卫生间" in n or "浴室" in n for n in room_names):
            checks.append({"category": "卫浴专项", "items": [
                "防水层闭水试验通过", "淋浴房玻璃无晃动",
                "浴室柜安装水平", "镜前灯接线规范",
            ]})

    return checks


def generate_construction_schedule(
    scene: Scene3D = None,
    start_date: str = None,
    duration_days: int = None,
) -> list[dict]:
    """
    生成施工进度计划，根据场景规模调整工期。

    Args:
        scene: Scene3D 对象（可选，有则推导工期）
        start_date: 开工日期 (YYYY-MM-DD)
        duration_days: 总工期 (可选，不传则从 scene 推导)

    Returns:
        施工阶段列表
    """
    if start_date is None:
        start = datetime.now()
    else:
        start = datetime.strptime(start_date, "%Y-%m-%d")

    # 从场景推导工期
    if scene and isinstance(scene, Scene3D):
        area = scene.total_floor_area_m2
        room_count = scene.room_count

        # 工期估算公式：基值 + 面积系数
        demo_days = max(3, int(area / 30))       # 拆除
        water_days = max(5, int(area / 15))       # 水电
        mason_days = max(10, int(area / 8))       # 泥瓦
        wood_days = max(7, int(area / 12))        # 木工
        paint_days = max(7, int(area / 10))       # 油漆
        install_days = max(5, int(area / 20))     # 安装
        check_days = max(2, int(room_count / 3))  # 验收
    elif duration_days:
        total = duration_days
        demo_days = max(3, int(total * 0.05))
        water_days = max(5, int(total * 0.12))
        mason_days = max(10, int(total * 0.23))
        wood_days = max(7, int(total * 0.17))
        paint_days = max(7, int(total * 0.17))
        install_days = max(5, int(total * 0.12))
        check_days = max(2, int(total * 0.03))
    else:
        # 默认值
        demo_days, water_days, mason_days = 3, 7, 14
        wood_days, paint_days, install_days, check_days = 10, 10, 7, 2

    phases = [
        ("拆除工程", demo_days, "拆墙、铲墙皮、垃圾清运"),
        ("水电改造", water_days, "开槽、布管、穿线、打压测试"),
        ("泥瓦工程", mason_days, "砌墙、防水、贴砖、找平"),
        ("木工进场", wood_days, "吊顶、背景墙、柜体制作"),
        ("油漆工程", paint_days, "批灰、打磨、底漆、面漆"),
        ("安装工程", install_days, "门、橱柜、开关插座、灯具"),
        ("竣工验收", check_days, "全面检查、整改、客户验收"),
    ]

    schedule = []
    current = start
    for name, days, desc in phases:
        end = current + timedelta(days=days)
        schedule.append({
            "phase": name,
            "start": current.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "days": days,
            "description": desc,
        })
        current = end + timedelta(days=1)

    total_days = sum(p["days"] for p in schedule) + len(schedule) - 1
    return schedule


def generate_daily_checklist(phase: str) -> list[str]:
    """生成每日施工现场检查项"""
    templates = {
        "拆除工程": [
            "确认拆除范围与图纸一致",
            "检查承重结构是否完好",
            "垃圾装袋堆放指定位置",
            "关闭非施工区域水电",
        ],
        "水电改造": [
            "核对水电点位与图纸一致",
            "检查管线走向是否规范",
            "打压测试压力是否达标",
            "强弱电间距>300mm",
        ],
        "泥瓦工程": [
            "检查防水涂层完整无漏刷",
            "闭水试验48小时无渗漏",
            "瓷砖排版是否合理",
            "检查瓷砖空鼓率",
        ],
        "油漆工程": [
            "检查基层平整度",
            "每遍腻子干透再施工",
            "底漆面漆间隔时间达标",
            "检查阴阳角顺直度",
        ],
    }
    return templates.get(phase, ["按图纸施工", "保持现场整洁", "做好成品保护"])
