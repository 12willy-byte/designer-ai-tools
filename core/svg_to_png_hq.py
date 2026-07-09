import os, re
from PIL import Image, ImageDraw, ImageFont
try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

def svg_to_png_hq(svg_path, png_path, scale=4, line_width_boost=1.5):
    """
    High-quality SVG to PNG conversion optimized for construction drawings.
    - scale: 4 = 4x resolution (A4 -> ~3300x2500px)
    - line_width_boost: multiplier for line thickness
    """
    if HAS_LXML:
        tree = etree.parse(svg_path)
        root = tree.getroot()
        
        # Boost all stroke-widths
        nsmap = {'svg': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
        for el in root.iter():
            sw = el.get('stroke-width', '')
            if sw:
                try:
                    new_sw = float(sw) * line_width_boost
                    el.set('stroke-width', str(round(new_sw, 1)))
                except ValueError:
                    pass
        
        # Get dimensions
        vb = root.get('viewBox', '')
        if not vb:
            w = root.get('width', '800').replace('px', '')
            h = root.get('height', '600').replace('px', '')
            vb = f'0 0 {w} {h}'
        
        parts = vb.split()
        if len(parts) >= 4:
            vb_w = float(parts[2]); vb_h = float(parts[3])
        else:
            vb_w = 800; vb_h = 600
        
        pil_w = int(vb_w * scale)
        pil_h = int(vb_h * scale)
        root.set('width', str(pil_w))
        root.set('height', str(pil_h))
        
        modified_svg = etree.tostring(root, encoding='unicode')
        
        import cairosvg
        cairosvg.svg2png(bytestring=modified_svg.encode('utf-8'),
                         write_to=png_path, output_width=pil_w, output_height=pil_h)
    else:
        from svg_to_png_pil import svg_to_png_pil
        svg_to_png_pil(svg_path, png_path, scale=scale, line_width_boost=line_width_boost)

def batch_convert_hq(svg_dir, png_dir, scale=4):
    os.makedirs(png_dir, exist_ok=True)
    results = []
    for f in sorted(os.listdir(svg_dir)):
        if f.endswith('.svg'):
            svg_path = os.path.join(svg_dir, f)
            png_path = os.path.join(png_dir, f.replace('.svg', '.png'))
            try:
                svg_to_png_hq(svg_path, png_path, scale=scale)
                results.append(png_path)
            except Exception as e:
                print(f'  Failed {f}: {e}')
                # Fallback to low-quality
                try:
                    from core.svg_to_png_pil import svg_to_png_pil
                    svg_to_png_pil(svg_path, png_path, scale=2)
                    results.append(png_path)
                except:
                    pass
    print(f'Converted {len(results)} SVGs to PNG (scale={scale}x)')
    return results
