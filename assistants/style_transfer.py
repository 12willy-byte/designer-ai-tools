# -*- coding: utf-8 -*-
"""
style_transfer - Design Style Transfer
Reference images -> DesignConditions (style, palette, materials, furniture, lighting)
Uses VLM for visual analysis + structured output mapping.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field
from core.data_model import DesignConditions, ProjectInfo, FamilyInfo, StylePreference, BudgetInfo

STYLE_ANALYSIS_PROMPT = """You are a senior interior designer. Analyze these reference images and extract detailed design specifications.

OUTPUT ONLY valid JSON:
{
  "style_analysis": {
    "primary_style": "modern_minimalist|new_chinese|nordic|japanese|industrial|french|american|eclectic",
    "style_keywords": ["keyword1","keyword2"],
    "spatial_feel": "open|cozy|luxurious|minimal|natural",
    "color_palette": {
      "base_colors": [{"hex":"#HEX","name":"name","ratio":0.6}],
      "secondary_colors": [{"hex":"#HEX","name":"name","ratio":0.3}],
      "accent_colors": [{"hex":"#HEX","name":"name","ratio":0.1}]
    },
    "materials": {
      "floor": {"type":"wood/tile/marble/concrete","color":"","finish":"matte/glossy/brushed","pattern":""},
      "wall": {"type":"paint/wallpaper/wood_panel/stone","color":"","finish":""},
      "ceiling": {"type":"flat/coffered/exposed/sloped","color":"","finish":""},
      "accent": {"type":"","color":"","area":"feature_wall/backsplash/niche"}
    },
    "furniture_style": {
      "silhouette": "slim/chunky/curved/angular",
      "leg_style": "tapered/straight/hairpin/none",
      "upholstery": "leather/fabric/velvet/linen",
      "wood_tone": "light/medium/dark/walnut/oak/ash"
    },
    "lighting_style": {
      "ambient": "recessed/track/pendant/chandelier",
      "task": "desk_lamp/under_cabinet/reading",
      "accent": "wall_sconce/cove/spotlight",
      "color_temp_k": 3000,
      "dimmer": true
    },
    "decorative_elements": ["plants","artwork","rugs","mirrors","textiles"],
    "layout_principles": ["open_plan","defined_zones","symmetry","flow_through"],
    "budget_indicators": {
      "level": "budget|mid_range|premium|luxury",
      "estimated_per_sqm": 0
    }
  },
  "applicable_rules": [
    {"rule":"furniture_scale","value":"Room proportion rule"},
    {"rule":"color_harmony","value":"60-30-10 rule"}
  ],
  "confidence": 0.9
}"""

def analyze_style_from_images(image_paths, ai_client=None):
    """
    Analyze reference images to extract design style.
    
    Args:
        image_paths: List of reference image file paths
        ai_client: Vision LLM client (GPT-4o / SenseNova-SI)
    
    Returns:
        Dict with style analysis or None if no client
    """
    if not ai_client:
        return _heuristic_style_analysis(image_paths)
    
    try:
        result = ai_client.analyze_multiple(image_paths, STYLE_ANALYSIS_PROMPT)
        if isinstance(result, str):
            result = json.loads(result)
        return result
    except Exception as e:
        print(f"[style_transfer] AI analysis failed: {e}, using heuristic")
        return _heuristic_style_analysis(image_paths)

def _heuristic_style_analysis(image_paths):
    """Fallback: extract basic style info from image colors."""
    from PIL import Image
    import numpy as np
    
    if not image_paths:
        return {
            "style_analysis": {
                "primary_style": "modern_minimalist",
                "color_palette": {"base_colors": [{"hex":"#FFFFFF","name":"white","ratio":0.6}],
                                  "secondary_colors": [{"hex":"#808080","name":"gray","ratio":0.3}],
                                  "accent_colors": [{"hex":"#000000","name":"black","ratio":0.1}]},
                "confidence": 0.3
            }
        }
    
    # Extract dominant colors from first image
    try:
        img = Image.open(image_paths[0]).convert('RGB')
        img = img.resize((100, 100))
        arr = np.array(img).reshape(-1, 3)
        
        # Simple k-means for dominant colors
        from collections import Counter
        quantized = (arr // 32) * 32
        colors = Counter([tuple(c) for c in quantized]).most_common(5)
        
        palette = []
        for color, count in colors[:5]:
            hex_c = '#{:02x}{:02x}{:02x}'.format(*color)
            palette.append({"hex": hex_c, "name": _color_name(color), "ratio": round(count/len(quantized), 2)})
        
        # Infer style from color characteristics
        avg_brightness = arr.mean()
        avg_saturation = np.std(arr, axis=0).mean() / 128
        
        if avg_brightness > 180 and avg_saturation < 0.2:
            style = "modern_minimalist"
        elif avg_brightness < 100:
            style = "industrial"
        elif avg_saturation > 0.4:
            style = "eclectic"
        else:
            style = "nordic"
        
        return {
            "style_analysis": {
                "primary_style": style,
                "color_palette": {
                    "base_colors": palette[:1],
                    "secondary_colors": palette[1:3],
                    "accent_colors": palette[3:5],
                },
                "confidence": 0.4
            }
        }
    except Exception:
        return {"style_analysis": {"primary_style": "modern_minimalist", "confidence": 0.2}}

def _color_name(rgb):
    """Simple color naming."""
    r, g, b = rgb
    if r > 200 and g > 200 and b > 200: return "white"
    if r < 50 and g < 50 and b < 50: return "black"
    if r > 150 and g < 100 and b < 100: return "red"
    if r < 100 and g > 150 and b < 100: return "green"
    if r < 100 and g < 100 and b > 150: return "blue"
    if r > 150 and g > 150 and b < 100: return "yellow"
    if abs(r-g) < 20 and abs(g-b) < 20:
        if r > 150: return "light gray"
        if r < 80: return "dark gray"
        return "gray"
    if r > 150 and g > 100 and b < 80: return "warm beige"
    if r > 120 and g > 120 and b > 120: return "warm white"
    return "neutral"

def style_to_design_conditions(style_analysis, project_name="New Project") -> DesignConditions:
    """
    Convert style analysis to DesignConditions object.
    
    Args:
        style_analysis: Dict from analyze_style_from_images
        project_name: Project name
    
    Returns:
        DesignConditions dataclass
    """
    sa = style_analysis.get("style_analysis", style_analysis)
    
    project = ProjectInfo(name=project_name, design_type=sa.get("primary_style", "modern_minimalist"))
    
    family = FamilyInfo(
        composition="待确认",
        storage_need="medium",
    )
    
    style = StylePreference(
        primary_style=sa.get("primary_style", "modern_minimalist"),
        color_tone=",".join([c.get("name","") for c in sa.get("color_palette",{}).get("base_colors",[])]) if sa.get("color_palette") else "",
        keywords=",".join(sa.get("style_keywords", [])),
        floor_material=sa.get("materials",{}).get("floor",{}).get("type","") if sa.get("materials") else "",
        wall_material=sa.get("materials",{}).get("wall",{}).get("type","") if sa.get("materials") else "",
        ceiling_type=sa.get("materials",{}).get("ceiling",{}).get("type","") if sa.get("materials") else "",
    )
    
    budget = BudgetInfo(
        total_budget=0,
        notes=f"AI estimated level: {sa.get('budget_indicators',{}).get('level','mid_range')}" if sa.get('budget_indicators') else ""
    )
    
    return DesignConditions(project=project, family=family, style=style, budget=budget)

def generate_style_guide(style_analysis, output_path=None):
    """
    Generate a readable style guide document from analysis.
    """
    sa = style_analysis.get("style_analysis", style_analysis)
    
    guide = f"""
=== DESIGN STYLE GUIDE ===

PRIMARY STYLE: {sa.get('primary_style', 'modern_minimalist').upper()}
Confidence: {sa.get('confidence', 0):.0%}

COLOR PALETTE:
{_format_palette(sa.get('color_palette', {}))}

MATERIALS:
  Floor: {_format_material(sa.get('materials', {}).get('floor', {}))}
  Wall: {_format_material(sa.get('materials', {}).get('wall', {}))}
  Ceiling: {_format_material(sa.get('materials', {}).get('ceiling', {}))}

FURNITURE STYLE:
{_format_furniture(sa.get('furniture_style', {}))}

LIGHTING:
  Ambient: {sa.get('lighting_style', {}).get('ambient', 'N/A')}
  Color Temp: {sa.get('lighting_style', {}).get('color_temp_k', 3000)}K

KEYWORDS: {', '.join(sa.get('style_keywords', []))}
LAYOUT: {', '.join(sa.get('layout_principles', []))}
"""
    
    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(guide)
    
    return guide

def _format_palette(palette):
    lines = []
    for role, colors in palette.items():
        if colors:
            for c in colors:
                lines.append(f"  {role}: {c.get('name','?')} ({c.get('hex','#000')}) - {c.get('ratio',0)*100:.0f}%")
    return '\n'.join(lines) if lines else '  N/A'

def _format_material(mat):
    if not mat: return 'N/A'
    return f"{mat.get('type','?')} / {mat.get('color','?')} / {mat.get('finish','?')}"

def _format_furniture(fs):
    if not fs: return '  N/A'
    return f"  Silhouette: {fs.get('silhouette','?')}\n  Leg: {fs.get('leg_style','?')}\n  Upholstery: {fs.get('upholstery','?')}\n  Wood: {fs.get('wood_tone','?')}"

def apply_style_to_scene(scene, style_analysis):
    """
    Apply style analysis to Scene3D.
    Updates scene.style, scene.color_palette, and applies material mappings.
    """
    sa = style_analysis.get("style_analysis", style_analysis)
    
    if hasattr(scene, 'style'):
        scene.style = sa.get("primary_style", scene.style)
    
    if hasattr(scene, 'color_palette') and sa.get("color_palette"):
        scene.color_palette = sa["color_palette"]
    
    # Apply material suggestions to rooms
    materials = sa.get("materials", {})
    if hasattr(scene, 'rooms'):
        for room in scene.rooms:
            rtype = getattr(room, 'type', '') if hasattr(room, 'type') else ''
            if not hasattr(room, 'finish'): continue
            if materials.get("floor"):
                room.finish["floor"] = materials["floor"].get("type", "")
            if materials.get("wall"):
                room.finish["wall"] = materials["wall"].get("type", "")
    
    return scene