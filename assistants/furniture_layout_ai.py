# -*- coding: utf-8 -*-
"""furniture_layout_ai - AI-driven furniture layout engine v2
Uses DeepSeek LLM + design rules + furniture catalog for room planning.
Falls back to enhanced rule engine when offline.
"""
import json, os, math, uuid, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.ai_client import get_client
from core.scene_utils import normalize as _n, get_rooms, get_walls, get_doors, get_windows

_RESOURCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")

def _load_json(filename):
    path = os.path.join(_RESOURCES_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

_CATALOG = None
_RULES = None

def _cat():
    global _CATALOG
    if _CATALOG is None: _CATALOG = _load_json("furniture_catalog.json")
    return _CATALOG

def _rul():
    global _RULES
    if _RULES is None: _RULES = _load_json("design_rules.json")
    return _RULES

ROOM_FURNITURE_MAP = {
    "客厅": ["沙发_三人","沙发_L型","沙发_双人","沙发_单人","沙发_意式极简","沙发_北欧布艺","茶几","电视柜","电视柜_悬浮","书柜","角几","单人休闲椅","展示柜","装饰壁炉","地毯_200x300","投影幕布_100寸","投影仪"],
    "living_room": ["沙发_三人","沙发_L型","沙发_双人","沙发_单人","沙发_意式极简","沙发_北欧布艺","茶几","电视柜","电视柜_悬浮","书柜","角几","单人休闲椅","展示柜","装饰壁炉","地毯_200x300","投影幕布_100寸","投影仪"],
    "主卧": ["双人床_1.8m","双人床_1.5m","床头柜","衣柜_三门","衣柜_双门","衣柜_四门","梳妆台","化妆台","电视柜","单人休闲椅","窗帘_电动"],
    "次卧": ["双人床_1.5m","单人床_1.2m","床头柜","衣柜_双门","书桌","梳妆台","儿童床_1.0m"],
    "卧室": ["双人床_1.5m","双人床_1.8m","单人床_1.2m","床头柜","衣柜_双门","衣柜_三门","衣柜_四门","梳妆台","化妆台","书桌","单人休闲椅","窗帘_电动"],
    "bedroom": ["双人床_1.5m","双人床_1.8m","单人床_1.2m","床头柜","衣柜_双门","衣柜_三门","衣柜_四门","梳妆台","化妆台","书桌","单人休闲椅","窗帘_电动"],
    "厨房": ["橱柜_地柜","冰箱_双门","冰箱_四门","洗碗机","蒸烤箱","烤箱嵌入式","油烟机","燃气灶","岛台","咖啡机嵌入式","净水器"],
    "kitchen": ["橱柜_地柜","冰箱_双门","冰箱_四门","洗碗机","蒸烤箱","烤箱嵌入式","油烟机","燃气灶","岛台","咖啡机嵌入式","净水器"],
    "卫生间": ["洗手台","马桶","智能马桶","壁挂马桶","淋浴房_900","浴缸","浴缸_独立式","洗衣机","浴柜","镜柜","花洒_恒温","毛巾架_电热"],
    "bathroom": ["洗手台","马桶","智能马桶","壁挂马桶","淋浴房_900","浴缸","浴缸_独立式","洗衣机","浴柜","镜柜","花洒_恒温","毛巾架_电热"],
    "餐厅": ["餐桌_6人","餐桌_4人","餐桌_8人","圆餐桌_6人","餐椅","餐边柜","吧台","岛台","酒柜"],
    "dining": ["餐桌_6人","餐桌_4人","餐桌_8人","圆餐桌_6人","餐椅","餐边柜","吧台","岛台","酒柜"],
    "书房": ["书桌","书桌_电动升降","书柜","单人床_1.2m","沙发_单人","角几","展示柜","按摩椅"],
    "study": ["书桌","书桌_电动升降","书柜","单人床_1.2m","沙发_单人","角几","展示柜","按摩椅"],
    "玄关": ["鞋柜","换鞋凳","玄关柜","屏风"],
    "走廊": [],
    "阳台": ["洗衣机","储物柜","百叶窗"],
}
SYSTEM_PROMPT = """You are a professional interior designer with 20 years of experience.

Design Principles (follow strictly):
1. CIRCULATION: Main walkways >= 900mm wide. Secondary paths >= 600mm. Never block doors.
2. FUNCTIONAL ZONES: Group furniture by function. Dining near kitchen. TV area with clear sightlines.
3. HUMAN ERGONOMICS: Bed sides >= 600mm. Toilet front >= 600mm. Sofa to TV: 2500-4000mm depending on screen. Dining chair pull-out: +600mm behind each chair.
4. NATURAL LIGHT: Don't block windows with tall furniture. Desks face windows when possible.
5. PROPORTION: Furniture should fit room scale. No oversized pieces in small rooms.
6. FOCAL POINTS: Each room needs a focal point (TV wall, bed headboard, window view).
7. STORAGE: Maximize storage without compromising circulation.
8. STYLE CONSISTENCY: Match furniture style to room style preference.

Coordinate System:
- X = right (mm), Z = forward (mm), Y = 0 (floor level)
- position is furniture CENTER point [x, 0, z]
- rotation: 0=facing +Z, 90=facing +X, 180=facing -Z, 270=facing -X

Room corners: SW(0,0) SE(length,0) NE(length,width) NW(0,width)

OUTPUT ONLY VALID JSON: {"placements": [{"name": "...", "position": [x, 0, z], "rotation": 0, "reason": "..."}]}"""

def _guideline(rt):
    g = {
        "客厅":"sofa against long wall, TV stand opposite, coffee table 400mm in front of sofa",
        "living_room":"sofa against long wall, TV stand opposite, coffee table 400mm in front of sofa",
        "主卧":"bed at back wall away from door, nightstands on both sides, wardrobe at entry wall",
        "卧室":"bed away from door wall, wardrobe at entry wall, keep walkway",
        "bedroom":"bed away from door wall, wardrobe at entry wall, keep walkway",
        "厨房":"cabinets L/U-shape along walls, fridge near entrance, sink at window, stove at exterior wall",
        "kitchen":"cabinets L/U-shape along walls, fridge near entrance, sink at window, stove at exterior wall",
        "卫生间":"vanity at entrance side, toilet 200mm+ from vanity, shower in corner",
        "bathroom":"vanity at entrance side, toilet 200mm+ from vanity, shower in corner",
        "餐厅":"dining table centered, 800mm+ from walls, chairs around",
        "dining":"dining table centered, 800mm+ from walls, chairs around",
    }
    return g.get(rt, "arrange based on room function")

def _build_prompt(rname, rtype, lmm, wmm, hmm, style, catalog_items):
    area = lmm * wmm / 1e6
    cat = _cat()
    items_db = cat.get("items", {})
    furn_opts = []
    for name in catalog_items:
        if name in items_db:
            item = items_db[name]
            furn_opts.append({
                "name": name,
                "dimensions_mm": "%dx%dx%d" % (item["w"], item["d"], item["h"]),
                "category": item.get("category", "")
            })
    
    return """Room: %s | Type: %s | Size: %.0fx%.0fx%.0fmm (%.1f sqm)
Style: %s

Available furniture:
%s

Output JSON: {"placements":[{"name":"...", "position":[x,0,z], "rotation":0, "reason":"..."}]}
Guideline: %s""" % (rname, rtype, lmm, wmm, hmm, area,
    style.get("primary_style", "modern"), json.dumps(furn_opts, ensure_ascii=False, indent=2),
    _guideline(rtype))

def _rule_layout(rname, rtype, lmm, wmm, hmm, style, family=None):
    cat = _cat()
    items_db = cat.get("items", {})
    hl, hw = lmm / 2, wmm / 2
    
    templates = {
        "客厅": [
            ("沙发_三人", [hl, 0, wmm-600], 180, "against long wall"),
            ("茶几", [hl, 0, wmm-1400], 0, "in front of sofa"),
            ("电视柜", [hl, 0, 200], 0, "TV wall centered"),
            ("地毯_200x300", [hl, 0, wmm-1400], 0, "under coffee area"),
            ("角几", [600, 0, wmm-600], 0, "beside sofa"),
        ],
        "主卧": [
            ("双人床_1.8m", [hl, 0, hw+500], 0, "back wall centered"),
            ("床头柜", [hl-1200, 0, hw+900], 0, "left of headboard"),
            ("床头柜", [hl+1200, 0, hw+900], 0, "right of headboard"),
            ("衣柜_三门", [300, 0, hw-300], 90, "entry wall"),
        ],
        "卧室": [
            ("双人床_1.5m", [hl, 0, hw+400], 0, "back wall"),
            ("床头柜", [hl-800, 0, hw+400], 0, "left of bed"),
            ("床头柜", [hl+800, 0, hw+400], 0, "right of bed"),
            ("衣柜_双门", [300, 0, hw-300], 90, "entry wall"),
            ("梳妆台", [wmm-300, 0, 300], 180, "near window"),
        ],
        "厨房": [
            ("橱柜_地柜", [hl*0.6, 0, hw-300], 0, "L-shape back"),("橱柜_地柜", [lmm-300, 0, hw*0.4], 90, "L-shape side"),
            ("冰箱_双门", [400, 0, 300], 90, "near entrance"),
        ],
        "卫生间": [
            ("洗手台", [hl, 0, 300], 180, "entry side"),
            ("马桶", [hl*0.6, 0, wmm-500], 0, "back of room"),
            ("淋浴房_900", [lmm-450, 0, wmm-450], 0, "far corner"),
        ],
        "餐厅": [
            ("餐桌_4人", [hl, 0, hw], 0, "centered"),
            ("餐椅", [hl-700, 0, hw], 90, "left"),
            ("餐椅", [hl+700, 0, hw], 270, "right"),
        ],
        "书房": [
            ("书桌", [hl, 0, hw], 180, "facing window"),
            ("书柜", [300, 0, hw], 90, "side wall"),
        ],
    }
    
    type_key = rtype
    for k in templates:
        if k in rtype or rtype in k:
            type_key = k; break
    
    tmpl = templates.get(type_key, templates.get("卧室", []))
    placements = []
    for name, pos, rot, reason in tmpl:
        fd = items_db.get(name, {})
        placements.append({
            "id": str(uuid.uuid4())[:8],
            "name": name, "category": fd.get("category", "general"),
            "position": pos, "rotation": rot,
            "width_mm": fd.get("w", 500), "depth_mm": fd.get("d", 500),
            "height_mm": fd.get("h", 750), "reason": reason, "room": rname,
        })
    return placements

REFINE_PROMPT = """You are a senior interior designer reviewing a furniture layout.

Current layout has these issues. Fix them:

1. ADJUST positions to resolve conflicts
2. REPLACE oversized furniture with smaller alternatives
3. ADD missing essential furniture for the room type
4. REMOVE unnecessary or redundant pieces
5. ENSURE all walkways meet minimum requirements
6. VERIFY furniture fits within room boundaries

Output ONLY valid JSON: {"placements": [{"name":"...", "position":[x,0,z], "rotation":0, "reason":"..."}]}
Include ALL furniture (both kept and adjusted)."""

def _validate_placements(placements, lmm, wmm):
    """Validate placements for conflicts and boundary issues.
    Returns list of issue descriptions."""
    issues = []
    for i, p1 in enumerate(placements):
        px, pz = p1["position"][0], p1["position"][2]
        hw1, hd1 = p1.get("width_mm",500)/2, p1.get("depth_mm",500)/2
        # Boundary check
        if px - hw1 < 0: issues.append(f'{p1["name"]} exceeds left wall by %.0fmm' % (hw1-px))
        if px + hw1 > lmm: issues.append(f'{p1["name"]} exceeds right wall by %.0fmm' % (px+hw1-lmm))
        if pz - hd1 < 0: issues.append(f'{p1["name"]} exceeds front wall by %.0fmm' % (hd1-pz))
        if pz + hd1 > wmm: issues.append(f'{p1["name"]} exceeds back wall by %.0fmm' % (pz+hd1-wmm))
        # Overlap check
        for j in range(i+1, len(placements)):
            p2 = placements[j]
            hw2, hd2 = p2.get("width_mm",500)/2, p2.get("depth_mm",500)/2
            ox, oz = p2["position"][0], p2["position"][2]
            if abs(px-ox) < (hw1+hw2+50) and abs(pz-oz) < (hd1+hd2+50):
                issues.append(f'{p1["name"]} overlaps {p2["name"]}')
    return issues

def _ai_layout_iterative(rname, rtype, lmm, wmm, hmm, style, family, catalog_items, client, max_iterations=3):
    """Iterative AI layout: generate -> validate -> force-fix -> refine -> repeat."""
    cat = _cat()
    items_db = cat.get("items", {})
    
    # Phase 1: Initial generation
    placements = _ai_layout(rname, rtype, lmm, wmm, hmm, style, family, catalog_items, client)
    
    for iteration in range(max_iterations):
        # Validate
        issues = _validate_placements(placements, lmm, wmm)
        if not issues:
            break
        
        print("[Layout] Iter %d: %d issues" % (iteration+1, len(issues)))
        
        # Phase A: Force-fix boundary issues (move items inside room)
        for p in placements:
            px, pz = p["position"][0], p["position"][2]
            hw = p.get("width_mm", 500) / 2
            hd = p.get("depth_mm", 500) / 2
            # Clamp to room boundaries with margin
            p["position"][0] = max(hw + 50, min(px, lmm - hw - 50))
            p["position"][2] = max(hd + 50, min(pz, wmm - hd - 50))
        
        # Phase B: Remove severely overlapping items
        to_remove = set()
        for i in range(len(placements)):
            if i in to_remove:
                continue
            p1 = placements[i]
            px1, pz1 = p1["position"][0], p1["position"][2]
            hw1, hd1 = p1.get("width_mm", 500)/2, p1.get("depth_mm", 500)/2
            for j in range(i+1, len(placements)):
                if j in to_remove:
                    continue
                p2 = placements[j]
                px2, pz2 = p2["position"][0], p2["position"][2]
                hw2, hd2 = p2.get("width_mm", 500)/2, p2.get("depth_mm", 500)/2
                overlap_x = (hw1 + hw2) - abs(px1 - px2)
                overlap_z = (hd1 + hd2) - abs(pz1 - pz2)
                if overlap_x > 100 and overlap_z > 100:
                    # Remove smaller/less important item
                    vol1 = hw1 * hd1 * p1.get("height_mm", 750)
                    vol2 = hw2 * hd2 * p2.get("height_mm", 750)
                    # Prefer keeping: bed > sofa > table > cabinet > chair > decor
                    priority = {"bed": 10, "sofa": 9, "table": 7, "cabinet": 6, "sanitary": 8, "appliance": 5, "chair": 4, "decor": 2, "general": 3}
                    cat1 = p1.get("category", "general")
                    cat2 = p2.get("category", "general")
                    score1 = priority.get(cat1, 3) * 1000 + vol1
                    score2 = priority.get(cat2, 3) * 1000 + vol2
                    if score1 >= score2:
                        to_remove.add(j)
                    else:
                        to_remove.add(i)
                        break
        
        if to_remove:
            removed_names = [placements[i]["name"] for i in sorted(to_remove, reverse=True)]
            placements = [p for i, p in enumerate(placements) if i not in to_remove]
            print("[Layout] Removed %d overlapping items: %s" % (len(to_remove), ", ".join(removed_names[:3])))
        
        # Check again after force-fix
        issues = _validate_placements(placements, lmm, wmm)
        if not issues:
            break
        
        # Phase C: AI refinement for remaining issues
        current = json.dumps({"placements": placements}, ensure_ascii=False, indent=2)
        feedback = "Remaining issues:\n" + "\n".join("- " + i for i in issues[:10])
        refine_request = "Room %s (%dx%dmm). Fix these issues:\n%s\nCurrent:\n%s\nOutput corrected JSON." % (rname, lmm, wmm, feedback, current)
        
        try:
            refined = client.chat_json(refine_request, REFINE_PROMPT)
            new_placements = refined.get("placements", [])
            if new_placements and len(new_placements) > 0:
                refined_map = {p["name"]: p for p in new_placements}
                for p in placements:
                    if p["name"] in refined_map:
                        rp = refined_map[p["name"]]
                        p["position"] = [max(hw+50, min(rp.get("position",[0,0,0])[0], lmm-hw-50)) for hw in [p.get("width_mm",500)/2]][0:1] + [0] + [max(hd+50, min(rp.get("position",[0,0,0])[2], wmm-hd-50)) for hd in [p.get("depth_mm",500)/2]][0:1]
                        p["position"][1] = 0
        except Exception as e:
            print("[Layout] Refine failed: %s" % e)
            break
    
    return placements


def _ai_layout(rname, rtype, lmm, wmm, hmm, style, family, catalog_items, client):
    prompt = _build_prompt(rname, rtype, lmm, wmm, hmm, style, catalog_items)
    result = client.chat_json(prompt, SYSTEM_PROMPT)
    cat = _cat()
    items_db = cat.get("items", {})
    placements = []
    for item in result.get("placements", []):
        name = item.get("name", "")
        pos = item.get("position", [0, 0, 0])
        rot = item.get("rotation", 0)
        reason = item.get("reason", "")
        fd = items_db.get(name, {})
        px = max(100, min(float(pos[0]), lmm - 100))
        pz = max(100, min(float(pos[2]), wmm - 100))
        placements.append({
            "id": str(uuid.uuid4())[:8],
            "name": name, "category": fd.get("category", "general"),
            "position": [px, 0, pz], "rotation": rot,
            "width_mm": fd.get("w", 500), "depth_mm": fd.get("d", 500),
            "height_mm": fd.get("h", 750), "reason": reason, "room": rname,
            "ai_generated": True,
        })
    return placements

def apply_ai_layout(scene, ai_client=None):
    """Apply AI-driven furniture layout to all rooms in Scene3D.
    
    Args:
        scene: Scene3D object
        ai_client: AIClient instance (auto-detected if None)
    
    Returns:
        list: all furniture placements
    """
    from core.scene3d import Furniture, Point3D
    
    if ai_client is None:
        ai_client = get_client()
    
    use_ai = ai_client.available
    
    style = getattr(scene, "style", {}) or {}
    family = getattr(scene, "family", {}) or {}
    rooms = get_rooms(scene)
    walls = get_walls(scene)
    
    all_placements = []
    
    for room in rooms:
        rd = _n(room)
        rname = rd.get("name", "room")
        rtype = rd.get("type", "living_room")
        rlen = rd.get("length_mm", 4000)
        rwid = rd.get("width_mm", 3500)
        rhei = rd.get("height_mm", 2800)
        
        catalog_items = ROOM_FURNITURE_MAP.get(rtype, ROOM_FURNITURE_MAP.get("living_room", ["沙发_三人", "茶几", "电视柜"]))
        
        if use_ai:
            try:
                placements = _ai_layout_iterative(rname, rtype, rlen, rwid, rhei, style, family, catalog_items, ai_client)
                print("[Layout] AI generated layout for %s (%d pieces)" % (rname, len(placements)))
            except Exception as e:
                print("[Layout] AI failed for %s: %s, using rules" % (rname, e))
                placements = _rule_layout(rname, rtype, rlen, rwid, rhei, style)
        else:
            print("[Layout] Offline mode - using rule engine for %s" % rname)
            placements = _rule_layout(rname, rtype, rlen, rwid, rhei, style)
        
        all_placements.extend(placements)
    
    # Apply to scene
    existing = set()
    if hasattr(scene, "furniture") and scene.furniture:
        furn = scene.furniture
        if isinstance(furn, dict):
            existing = {f.name for f in furn.values()}
        elif isinstance(furn, list):
            existing = {f.name for f in furn}
    
    for p in all_placements:
        # Avoid duplicates
        if p["name"] in existing:
            continue
        
        furn = Furniture(
            id=p["id"],
            name=p["name"],
            category=p["category"],
            position=Point3D(p["position"][0], p["position"][1], p["position"][2]),
            rotation_deg=p["rotation"],
            width_mm=p["width_mm"],
            depth_mm=p["depth_mm"],
            height_mm=p["height_mm"],
            room_id=p["room"],
        )
        
        if not hasattr(scene, "furniture"):
            scene.furniture = []
        if isinstance(scene.furniture, list):
            scene.furniture.append(furn)
        elif isinstance(scene.furniture, dict):
            scene.furniture[furn.id] = furn
        
        existing.add(p["name"])
    
    print("[Layout] Total: %d furniture placed in %d rooms" % (len(all_placements), len(rooms)))
    return all_placements


# Compatibility aliases
def _coord(p, a=0):
    if isinstance(p, (list, tuple)): return p[a]
    if isinstance(p, dict): return p.get(("x", "y", "z")[a], 0)
    if hasattr(p, ("x", "y", "z")[a]): return getattr(p, ("x", "y", "z")[a])
    return 0

print("furniture_layout_ai v2 ready - AI-driven with %d room types" % len(ROOM_FURNITURE_MAP))
