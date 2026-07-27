"""Step 3: 材质方案生成器
输入: 设计条件.json
输出: 材质推荐数据 + 材质板图片
"""
import json, os, sys, re
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from core.ai_client import get_client
from core.design_schema import normalize_conditions

SYSTEM_PROMPT = """你是中国顶尖的室内设计材质专家。根据客户需求，为每个空间推荐具体的材质搭配。

请按以下 JSON 格式输出（只输出 JSON，不要多余文字）：

{
  "design_concept": "材质搭配理念简述",
  "materials": [
    {
      "room": "客厅",
      "floor": {"type":"橡木地板","color":"浅原木色","finish":"哑光","code":""},
      "wall": {"type":"艺术涂料","color":"暖白色","finish":"蛋壳光","code":""},
      "feature_wall": {"type":"木格栅","color":"原木色","finish":"开放漆","code":""},
      "ceiling": {"type":"乳胶漆","color":"白色","finish":"哑光","code":""},
      "notes": "地面通铺橡木地板延伸空间感"
    }
  ],
  "global_recommendations": {
    "door_material": {"type":"平板门","color":"暖白","finish":"烤漆"},
    "door_hardware": "黑色哑光",
    "window_frame": "断桥铝 深灰色",
    "baseboard": "实木 浅橡木色 60mm高",
    "cabinet_face": "PET 肤感暖白"
  },
  "color_palette_link": "与之前推荐的暖灰白+雾霾蓝+陶土橙一致",
  "assumptions": ["假设：……（本方案中所有推断集中列在这里）"]
}

【事实与假设边界 — 必须严格遵守】
1. 空间事实：只为输入中列出的房间生成材质方案，不得新增、合并或改写输入中不存在的空间；户型与房间数量以输入为准。
2. 品牌与型号：输入未提供品牌偏好时，禁止编造具体品牌名和型号。每个材质条目只描述材质/颜色/工艺，"code" 字段留空或填价位档（如"ENF级颗粒板，约260元/㎡"）。
   如确需举例帮助客户理解，必须写成"示例品牌，可替换：XX"，且示例品牌放在 notes 中，不得出现在 type/code 字段。
3. 推断集中标注：凡输入未直接给出的信息（家庭成员年龄推断、生活习惯推断、未确认的现场条件等），不得写进 materials 的描述性文字里与事实混排，统一放入顶层 "assumptions" 数组，每条以"假设："开头；没有推断时输出空数组。
4. 面积口径：引用总面积时以输入的建筑面积为准；如引用房间面积加总，必须注明"房间加总约XX㎡（不含公摊/墙体）"。"""


# 输出契约：交给 core.output_defense 做归一化/降级。
# "object:type" 表示该槽位必须是对象；模型若返回纯字符串（如 "木地板"），
# 统一防御层会包装为 {"type": "木地板"} 并留痕（收口此前的点状防御 _as_material）。
MATERIAL_CONTRACT = {
    "design_concept": "str",
    "materials": [{
        "room": "str",
        "floor": "object:type",
        "wall": "object:type",
        "feature_wall": "object:type",
        "ceiling": "object:type",
        "notes": "str",
    }],
    "global_recommendations": "object",
    "assumptions": "list",
}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))


def generate_material_board(conditions_json_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = normalize_conditions(json.load(f))

    style = conditions.get("style", {})
    space = conditions.get("space_data", {})
    budget = conditions.get("budget", {})
    rooms_req = conditions.get("rooms_requirements", {})
    project = conditions.get("project", {})

    prompt = "请为以下项目推荐材质方案：\n\n"
    prompt += "风格: %s\n" % style.get("primary_style","未指定")
    prompt += "色调: %s\n" % style.get("color_tone","未指定")
    prompt += "设计关键词: %s\n" % style.get("keywords","")

    building_area = project.get("area_m2") or project.get("area")
    if building_area:
        prompt += "建筑面积(输入口径，总面积以此为准): %s m2\n" % building_area
    if space.get("total_area_m2"):
        prompt += "房间加总约 %.1f m2（不含公摊/墙体，仅供参考）\n" % space["total_area_m2"]

    # 品牌偏好：输入未提供时明确告知模型，禁止编造品牌型号
    brand_pref = style.get("brand_preference") or style.get("brand") or ""
    if brand_pref:
        prompt += "品牌偏好: %s\n" % brand_pref
    else:
        prompt += "品牌偏好: 输入未提供 —— 禁止编造具体品牌名和型号，只描述材质/颜色/工艺/价位档\n"

    if space.get("rooms"):
        prompt += "\n空间列表（输入事实，只为这些房间生成方案，不得增减）:\n"
        for rm in space["rooms"]:
            req = rooms_req.get(rm["name"], {})
            prompt += "- %s (%d x %d mm)" % (rm["name"], rm["width_mm"], rm["height_mm"])
            for k,v in req.items():
                if v: prompt += "  %s: %s" % (k, v)

    if budget:
        prompt += "\n预算参考:\n"
        for k,v in budget.items():
            if isinstance(v, dict) and v.get("amount"):
                prompt += "- %s: %.0f元"%(v.get("item",k), v["amount"])

    # 墙面/地面材质偏好
    wall_pref = style.get("wall_material","")
    floor_pref = style.get("floor_material","")
    if wall_pref: prompt += "\n墙面偏好: %s" % wall_pref
    if floor_pref: prompt += "\n地面偏好: %s" % floor_pref

    client = get_client()
    # 统一防御层：材质槽位必须是对象（真实模型曾把 floor/wall 返回纯字符串
    # 导致渲染与预算匹配崩溃）；漂移由 output_defense 归一化并留痕。
    data = client.chat_json(
        SYSTEM_PROMPT, prompt, temperature=0.6, max_tokens=2500,
        contract=MATERIAL_CONTRACT,
        context="step3_material_board",
    )

    # 生成材质板图片
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    os.makedirs(out_dir, exist_ok=True)

    img_path = render_material_board(data, out_dir)
    data["board_image"] = img_path
    with open(os.path.join(out_dir, "材质方案.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


MATERIAL_COLORS = {
    "橡木": "#D4A76A", "胡桃木": "#5C3A1E", "黑胡桃": "#3E2723",
    "白橡": "#D7C4A1", "柚木": "#8B5E3C",
    "橡木地板": "#D4A76A", "木地板": "#C4956A",
    "瓷砖": "#D4D4D4", "柔光砖": "#D0D0D0", "仿木纹砖": "#C4956A",
    "岩板": "#A0A0A0", "石材": "#B8B8B8", "大理石": "#E8E0D8",
    "石英石": "#E0E0E0", "不锈钢": "#C0C0C0",
    "乳胶漆": "#F0EDE8", "艺术涂料": "#E8E2D8", "微水泥": "#C8C0B8",
    "木饰面": "#D4A76A", "木格栅": "#C4956A",
    "玻璃": "#D8E8F0", "长虹玻璃": "#C8D8E0",
    "金属": "#B0B0B0", "铝": "#A0A8B0",
    "布艺": "#D0C8C0", "皮革": "#8B6540",
    "PET": "#E8E0D8", "烤漆": "#E8E0D8", "肤感": "#E8E0D8",
    "白色": "#F5F0EB", "暖白": "#F5F0EB",
    "灰色": "#B0B0B0", "深灰": "#707070",
    "黑色": "#333333", "深色": "#444444",
    "原木色": "#D4A76A", "浅原木": "#DEC8A8",
}

# 全局材质建议字段的中文标签（避免交付图上出现原始 JSON 键名）
_GLOBAL_REC_LABELS = {
    "door_material": "室内门",
    "door_hardware": "门五金",
    "window_frame": "窗框",
    "baseboard": "踢脚线",
    "cabinet_face": "柜体饰面",
}


def render_material_board(data, output_dir):
    width, height = 1400, 900
    img = Image.new("RGB", (width, height), "#FAFAF8")
    draw = ImageDraw.Draw(img)

    from core.font_utils import load_cjk_font
    font_l = load_cjk_font(30)
    font_m = load_cjk_font(22)
    font_s = load_cjk_font(17)

    draw.text((40, 25), "材质方案", fill="#333", font=font_l)
    concept = data.get("design_concept","")
    if concept:
        draw.text((40, 68), concept[:60], fill="#888", font=font_m)

    materials = data.get("materials",[])
    y_start = 120
    card_w = 420
    card_h = 320
    gap_x = 25
    gap_y = 25
    cols = 3

    def get_color(text):
        text = str(text) if text else ""
        for key, val in MATERIAL_COLORS.items():
            if key in text:
                return hex_to_rgb(val)
        return hex_to_rgb("#D0C8B8")

    # 槽位结构已由 chat_json 契约（MATERIAL_CONTRACT）保证为对象，
    # 点状防御已收口到 core.output_defense 统一层。
    for i, mat in enumerate(materials):
        if not isinstance(mat, dict):
            continue
        col = i % cols
        row = i // cols
        x = 40 + col * (card_w + gap_x)
        y = y_start + row * (card_h + gap_y)

        # 卡背景
        draw.rectangle([x, y, x+card_w, y+card_h], fill="white", outline="#E0E0E0")

        # 房间名
        room_name = mat.get("room","")
        draw.text((x+15, y+12), room_name, fill="#333", font=font_m)

        # 材质条目
        items = [
            ("地面", mat.get("floor") or {}),
            ("墙面", mat.get("wall") or {}),
            ("背景墙", mat.get("feature_wall") or {}),
            ("天花", mat.get("ceiling") or {}),
        ]

        iy = y + 50
        for label, item in items:
            if not item or not item.get("type"):
                continue
            ic = get_color("%s %s" % (item.get("type",""), item.get("color","")))
            draw.rectangle([x+15, iy, x+45, iy+20], fill=ic, outline="#DDD")
            draw.text((x+52, iy-2), "%s: %s" % (label, item.get("type","")), fill="#444", font=font_s)
            color_str = item.get("color","")
            finish_str = item.get("finish","")
            extra = color_str
            if finish_str: extra += ", %s" % finish_str
            if extra.strip(","):
                draw.text((x+52, iy+18), extra, fill="#999", font=font_s)
            iy += 52

        # 备注
        notes = mat.get("notes","")
        if notes:
            draw.text((x+15, y+card_h-28), notes[:25], fill="#888", font=font_s)

    # 全局推荐
    global_rec = data.get("global_recommendations",{})
    if global_rec:
        yr = y_start + ((len(materials)-1)//cols + 1) * (card_h + gap_y) + 20
        draw.text((40, yr), "全局材质建议", fill="#333", font=font_m)
        ry = yr + 40
        for key, val in global_rec.items():
            label = _GLOBAL_REC_LABELS.get(key, key)
            if isinstance(val, dict):
                text = "%s: %s %s" % (label, val.get("type",""), val.get("color",""))
            else:
                text = "%s: %s" % (label, val)
            draw.text((60, ry), text, fill="#555", font=font_s)
            ry += 30

    path = os.path.join(output_dir, "材质方案.png")
    img.save(path)
    return path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    r = generate_material_board(inp)
    mats = r.get("materials",[])
    print("材质方案: %s" % r.get("design_concept",""))
    for m in mats:
        print("  %s: 地面=%s 墙面=%s" % (
            m.get("room",""),
            m.get("floor",{}).get("type",""),
            m.get("wall",{}).get("type","")))
    print("图片:", r.get("board_image",""))
