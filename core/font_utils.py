"""Cross-platform CJK font loading for Pillow renderers.

The pipeline's PNG renderers previously hard-coded a Windows font path, so on
macOS/Linux all Chinese text fell back to PIL's default bitmap font and
rendered as boxes. Use load_cjk_font() to try platform candidates in order.
"""
from PIL import ImageFont

CJK_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",                        # Windows 微软雅黑
    "C:/Windows/Fonts/simsun.ttc",                      # Windows 宋体
    "/System/Library/Fonts/PingFang.ttc",               # macOS 苹方
    "/System/Library/Fonts/STHeiti Light.ttc",          # macOS 黑体
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",     # Linux 文泉驿
]


def load_cjk_font(size):
    """Return the first available CJK-capable TrueType font, or PIL default."""
    for path in CJK_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()
