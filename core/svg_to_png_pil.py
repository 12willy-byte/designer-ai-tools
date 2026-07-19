# -*- coding: utf-8 -*-
"""svg_to_png_pil.py - Pure Python SVG-to-PNG converter using PIL/Pillow + lxml.
No native C libraries required beyond what's already installed.
"""
import os, math, re
from lxml import etree
from PIL import Image, ImageDraw, ImageFont

def parse_unit(s):
    """Parse a dimension string like '3px', '2.5mm', '100' to a float."""
    s = str(s).strip()
    s = re.sub(r'[a-zA-Z%]+$', '', s)
    try:
        return float(s)
    except ValueError:
        return 0

def get_color(fill_str, default=None):
    """Parse a CSS color string to RGBA tuple. Returns None for 'none'."""
    if not fill_str or fill_str == "none":
        return None
    if fill_str == "url(#hatch)":
        return (200, 200, 200, 255)
    if fill_str.startswith("#"):
        h = fill_str.lstrip("#")
        if len(h) == 3:
            h = "".join(c*2 for c in h)
        if len(h) == 6:
            return tuple(int(h[i:i+2], 16) for i in (0,2,4)) + (255,)
    if fill_str.startswith("rgb"):
        nums = re.findall(r'\d+', fill_str)
        if len(nums) >= 3:
            return tuple(int(n) for n in nums[:3]) + (255,)
    named = {
        "white": (255,255,255,255), "black": (0,0,0,255),
        "red": (255,0,0,255), "blue": (0,0,255,255),
        "green": (0,255,0,255), "gray": (128,128,128,255),
        "yellow": (255,255,0,255), "cyan": (0,255,255,255),
        "magenta": (255,0,255,255), "orange": (255,165,0,255),
        "silver": (192,192,192,255), "maroon": (128,0,0,255),
        "purple": (128,0,128,255), "navy": (0,0,128,255),
        "lime": (0,255,0,255), "teal": (0,128,128,255),
        "aqua": (0,255,255,255), "fuchsia": (255,0,255,255),
    }
    return named.get(fill_str.lower())


def svg_to_png(svg_path, png_path=None, scale=2):
    """Convert SVG to PNG using PIL. Returns png_path or None."""
    if png_path is None:
        png_path = svg_path.replace(".svg", ".png")
    
    try:
        tree = etree.parse(svg_path)
        root = tree.getroot()
        
        svg_ns = "http://www.w3.org/2000/svg"
        vb = root.get("viewBox", "")
        width_str = root.get("width", "800")
        height_str = root.get("height", "600")
        
        if vb:
            parts = vb.split()
            if len(parts) == 4:
                vb_x, vb_y, vb_w, vb_h = map(float, parts)
            else:
                vb_w, vb_h = parse_unit(width_str), parse_unit(height_str)
        else:
            vb_w, vb_h = parse_unit(width_str), parse_unit(height_str)
        
        img_w = max(1, int(vb_w * scale))
        img_h = max(1, int(vb_h * scale))
        
        img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        
        # Parse CSS
        styles = {}
        for style_el in root.findall(f"{{{svg_ns}}}style"):
            css_text = style_el.text or ""
            for rule in css_text.split("}"):
                if "{" not in rule:
                    continue
                selector, props = rule.split("{", 1)
                selector = selector.strip().lstrip(".")
                style_dict = {}
                for prop in props.split(";"):
                    if ":" in prop:
                        k, v = prop.split(":", 1)
                        style_dict[k.strip()] = v.strip()
                styles[selector] = style_dict
        
        def get_class_style(el):
            cls = el.get("class", "")
            result = {}
            for c in cls.split():
                if c in styles:
                    result.update(styles[c])
            return result
        
        # Scale helpers
        S = scale
        
        # Render elements
        for el in root.iter():
            tag = etree.QName(el).localname
            cs = get_class_style(el)
            
            fill_str = el.get("fill") or cs.get("fill", "")
            stroke_str = el.get("stroke") or cs.get("stroke", "")
            stroke_w = parse_unit(el.get("stroke-width") or cs.get("stroke-width", "1")) * S
            
            fill_color = get_color(fill_str)
            stroke_color = get_color(stroke_str, "black")
            
            if tag in ("style", "defs", "pattern", "g", "svg"):
                continue
            
            elif tag == "line":
                x1 = parse_unit(el.get("x1","0")) * S
                y1 = parse_unit(el.get("y1","0")) * S
                x2 = parse_unit(el.get("x2","0")) * S
                y2 = parse_unit(el.get("y2","0")) * S
                if stroke_color:
                    draw.line([(x1, y1), (x2, y2)], fill=stroke_color[:3], width=max(1, int(stroke_w)))
            
            elif tag == "rect":
                x = parse_unit(el.get("x","0")) * S
                y = parse_unit(el.get("y","0")) * S
                w = parse_unit(el.get("width","0")) * S
                h = parse_unit(el.get("height","0")) * S
                coords = [(x, y), (x+w, y+h)]
                if fill_color:
                    draw.rectangle(coords, fill=fill_color[:3])
                if stroke_color:
                    draw.rectangle(coords, outline=stroke_color[:3], width=max(1, int(stroke_w)))
            
            elif tag == "circle":
                cx = parse_unit(el.get("cx","0")) * S
                cy = parse_unit(el.get("cy","0")) * S
                r = parse_unit(el.get("r","0")) * S
                bbox = [(cx-r, cy-r), (cx+r, cy+r)]
                if fill_color:
                    draw.ellipse(bbox, fill=fill_color[:3])
                if stroke_color:
                    draw.ellipse(bbox, outline=stroke_color[:3], width=max(1, int(stroke_w)))
            
            elif tag in ("polygon", "polyline"):
                pts_str = el.get("points","")
                pts = []
                for p in pts_str.split():
                    if "," in p:
                        px, py = p.split(",")
                        pts.append((parse_unit(px) * S, parse_unit(py) * S))
                if len(pts) >= 2:
                    if fill_color:
                        draw.polygon(pts, fill=fill_color[:3])
                    if stroke_color:
                        draw.line(pts + [pts[0]], fill=stroke_color[:3], width=max(1, int(stroke_w)))
            
            elif tag == "text":
                x = parse_unit(el.get("x","0")) * S
                y = parse_unit(el.get("y","0")) * S
                text = el.text or ""
                font_size = max(8, int(parse_unit(el.get("font-size") or cs.get("font-size", "3")) * S))
                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except:
                    try:
                        font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", font_size)
                    except:
                        font = ImageFont.load_default()
                if fill_color:
                    draw.text((x, y), text, fill=fill_color[:3], font=font)
        
        # Save
        os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
        img = img.convert("RGB")
        img.save(png_path, "PNG")
        return png_path
    
    except Exception as e:
        print(f"svg_to_png_pil error: {e}")
        import traceback
        traceback.print_exc()
        return None
