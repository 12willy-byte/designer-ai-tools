"""Step 1: 设计定位文案生成器
输入: 设计条件.json
输出: 设计定位文案 + 设计关键词
"""
import json, os, sys
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

SYSTEM_PROMPT = """你是中国顶尖的室内设计文案专家。你的任务是根据客户需求数据和空间扫描数据，撰写专业的设计定位说明。

你需要输出的内容包括：
1. 设计定位说明（200-300字，描述整体设计理念、氛围、风格方向）
2. 3-5个设计关键词
3. 设计调性概述（用3组对比词描述，如：温馨/理性、简约/丰富）

要求：
- 语言专业但不晦涩，让客户也能看懂
- 结合空间实际尺寸做合理的设计建议
- 体现对客户生活方式的理解
- 符合中国室内设计行业术语习惯
"""


def generate_design_brief(conditions_json_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    project = conditions.get("project", {})
    style = conditions.get("style", {})
    family = conditions.get("family", {})
    space = conditions.get("space_data", {})
    rooms_req = conditions.get("rooms_requirements", {})

    pieces = []
    pieces.append("=== 项目概况 ===")
    pieces.append("项目名称: %s" % project.get("name","未命名"))
    pieces.append("房屋类型: %s" % project.get("house_type","未指定"))
    pieces.append("建筑面积: %s m2" % (project.get("area") or space.get("total_area_m2","未知")))

    pieces.append("\n=== 家庭成员与生活方式 ===")
    for k,v in family.items():
        if v: pieces.append("%s: %s"%(k,v))

    pieces.append("\n=== 风格偏好 ===")
    for k,v in style.items():
        if v: pieces.append("%s: %s"%(k,v))

    pieces.append("\n=== 空间数据 ===")
    if space.get("rooms"):
        pieces.append("共 %d 个房间，总面积 %.1f m2"%(space["total_rooms"],space["total_area_m2"]))
        for rm in space["rooms"]:
            pieces.append("- %s: %d x %d mm (%.1f m2)"%(rm["name"],rm["width_mm"],rm["height_mm"],rm["area_m2"]))
    if space.get("has_beams"): pieces.append("- 有梁结构，需考虑吊顶处理")
    if space.get("has_columns"): pieces.append("- 有结构柱，需考虑包柱设计")

    pieces.append("\n=== 各空间设计需求 ===")
    for room_name, reqs in rooms_req.items():
        filled = {k:v for k,v in reqs.items() if v}
        if filled:
            pieces.append("- %s:"%room_name)
            for k,v in filled.items():
                pieces.append("    %s: %s"%(k,v))

    pieces.append("\n=== 特殊需求 ===")
    special = conditions.get("special_requirements",{})
    for k,v in special.items():
        if v: pieces.append("%s: %s"%(k,v))

    user_prompt = "\n".join(pieces)

    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":user_prompt},
        ],
        temperature=0.7,
        max_tokens=2000,
    )

    content = resp.choices[0].message.content
    return {"raw_text": content, "design_brief": content}


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv)>1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv)>2 else None
    result = generate_design_brief(inp)
    print(result["raw_text"])
    if out:
        with open(out,"w",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
        print("\nSaved:",out)
