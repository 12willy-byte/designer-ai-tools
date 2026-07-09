"""
VLM 空间视觉分析器
路线一: SenseNova-SI / GPT-4o 理解照片中的空间语义
路线二: 对接 CAD 精确尺寸生成完整设计条件
"""
import os, sys, json, math, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.ai_client import get_vision

SYSTEM_SPATIAL = """You are an expert architectural space analyzer. Examine interior photos and extract precise spatial information: room type, structural elements (walls/doors/windows/beams/columns/pipes with positions), floor material, ceiling type, approximate dimensions (use door height ~2100mm as reference), lighting conditions. Output ONLY valid JSON."""

SYSTEM_STYLE = """You are an expert interior design style analyst. Examine reference images and extract: primary style, color palette (hex codes), key materials, furniture style, lighting style, decorative elements, layout principles. Output ONLY valid JSON."""


def analyze_room_photos(image_paths, provider="sensenova"):
    """分析房间照片，提取空间结构数据"""
    client = get_vision(provider)
    question = """Analyze these interior photos. Output JSON:
{
  "room_type": "living_room/kitchen/bedroom/bathroom/hallway/balcony",
  "estimated_dimensions": {"width_mm": 0, "depth_mm": 0, "height_mm": 2800},
  "structural_elements": {
    "walls": [{"position": "north/south/east/west", "length_mm": 0}],
    "doors": [{"position": "...", "width_mm": 900, "swing": "inward/outward"}],
    "windows": [{"position": "...", "width_mm": 0, "height_mm": 0, "sill_height_mm": 0}],
    "beams": [{"position": "...", "depth_mm": 0}],
    "columns": [{"position": "...", "width_mm": 0, "depth_mm": 0}],
    "pipes": [{"position": "...", "diameter_mm": 0, "type": "water/gas/drain"}]
  },
  "floor_material": "tile/wood/concrete/other",
  "ceiling_type": "flat/coffered/exposed/sloped",
  "natural_light_direction": "north/south/east/west/none",
  "obstructions": [],
  "confidence": 0.85
}
Use door height (~2100mm) as primary scale reference."""

    if len(image_paths) == 1:
        return client.chat_json(image_paths[0], question, SYSTEM_SPATIAL)
    raw = client.analyze_multiple(image_paths, question, SYSTEM_SPATIAL)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m: return json.loads(m.group(1))
    return {"raw": raw, "parse_error": True}


def analyze_style_reference(image_paths, provider="sensenova"):
    """分析参考效果图，提取风格属性"""
    client = get_vision(provider)
    question = """Analyze these interior design reference images. Output JSON:
{
  "primary_style": "modern_minimalist/new_chinese/nordic/japanese/french/industrial/american/eclectic",
  "color_palette": [{"hex": "#HEX", "name": "name", "role": "base/secondary/accent"}],
  "materials": {"floor": "", "wall": "", "furniture": "", "ceiling": ""},
  "furniture_style": "",
  "lighting_style": "",
  "decorative_elements": [],
  "layout_principles": "",
  "spatial_feel": "open/cozy/luxurious/minimal"
}"""

    if len(image_paths) == 1:
        return client.chat_json(image_paths[0], question, SYSTEM_STYLE)
    raw = client.analyze_multiple(image_paths, question, SYSTEM_STYLE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m: return json.loads(m.group(1))
    return {"raw": raw, "parse_error": True}


def merge_vision_with_cad(vision_data, cad_data):
    """合并 VLM 视觉分析 + CAD 精确数据 -> 完整设计条件"""
    return {
        "room_type": vision_data.get("room_type", ""),
        "vlm_estimated": vision_data.get("estimated_dimensions", {}),
        "cad_precise": {
            "bounds": cad_data.get("bounds", ()),
            "wall_count": len(cad_data.get("walls", [])),
            "text_labels": [t["text"] for t in cad_data.get("texts", [])[:10]],
        },
        "structural": vision_data.get("structural_elements", {}),
        "materials": {
            "floor": vision_data.get("floor_material", ""),
            "ceiling": vision_data.get("ceiling_type", ""),
        },
        "light": vision_data.get("natural_light_direction", ""),
        "confidence": vision_data.get("confidence", 0),
        "source": "VLM+CAD",
    }


def spatial_qa(image_path, question, provider="sensenova"):
    """空间问答：客户拍照提问，AI 结合空间推理回答"""
    client = get_vision(provider)
    system = "You are an interior design spatial consultant. Answer questions about the room in the photo using spatial reasoning. Use standard door height 2100mm as reference. Be honest when you cannot determine something."
    return client.analyze_image(image_path, question, system)
