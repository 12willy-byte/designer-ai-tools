"""PDF 内容流门扇弧线提取 —— pdfminer/pdfplumber 丢失的符号实例回收。

背景（真实图纸实测）：CAD 导出的矢量 PDF 常把门扇摆动弧线画成"局部 cm
矩阵 + 相对三次贝塞尔（圆弧贝塞尔常数 κ≈0.552）"的符号实例。pdfminer 的
CTM 复合方向与这类文件的实际渲染结果不一致（渲染器按 CTM' = CTM × M
复合），导致这些符号在 pdfplumber 的对象模型里落到版心之外被丢弃——
门扇弧线在 page.curves 里根本不存在。

本模块直接解释页面内容流：
1. 迷你 tokenizer（数字含科学计数、字符串、内联图像 BI..EI 跳过）；
2. 图形状态机：q/Q 栈、cm 按渲染器语义复合（CTM' = CTM × M）、
   m/l/c/v/y 路径算子，重建每条三次贝塞尔的页面用户空间坐标；
3. 按 /Rotate 与 MediaBox 映射到 pdfplumber 一致的"y 轴向上"坐标；
4. 圆弧判定：贝塞尔 8 点采样 + Kasa 代数圆拟合（残差 ≤10%），
   扫掠角 55°–135°、半径在门宽量级（默认 45–220pt）；
5. 家具整圆剔除：同一圆心 ≥3 段弧或累计扫掠 ≥270° 的是圆桌/洁具整圆，
   不是门扇弧线。

输出每条弧：铰链点（圆心）、半径（≈门宽）、门板端点 p0、关闭位置 p3、
扫掠角。坐标单位 pt（y 轴向上），调用方按 pt_to_mm 换算。

诚实边界：只提取"圆弧形贝塞尔"，推拉门/折叠门无弧线表达，识别不到；
弧线只证明"这里画了门符号"，不证明墙体真实可开洞。
"""
import math
import re

import pypdf


# ---------------------------------------------------------------- 内容流解释

_TOKEN_NUM = re.compile(rb"-?\d*\.?\d+(?:[eE][+-]?\d+)?")
_TOKEN_NAME = re.compile(rb"/[^\s\[\]<>()/%]+")
_TOKEN_OP = re.compile(rb"[A-Za-z\*'\"]+")
_SKIP_WS = b" \t\r\n\x0c\x00"
_PATH_END_OPS = frozenset(
    ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n", "h", "re", "W", "W*"))


def _tokenize(data):
    """切分内容流；内联图像 BI..EI 段整体剔除（其字节会污染算子流）。"""
    i, n = 0, len(data)
    toks = []
    while i < n:
        c = data[i:i + 1]
        if c in _SKIP_WS:
            i += 1
            continue
        if c == b"%":
            j = data.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        if data[i:i + 2] in (b"<<", b">>"):
            toks.append(("op", data[i:i + 2].decode()))
            i += 2
            continue
        if c == b"/":
            m = _TOKEN_NAME.match(data[i:])
            toks.append(("name", m.group()))
            i += len(m.group())
            continue
        if c in b"[]":
            toks.append(("op", c.decode()))
            i += 1
            continue
        if c == b"(":  # 字符串（可含转义与嵌套括号）
            depth, j = 1, i + 1
            while j < n and depth:
                ch = data[j:j + 1]
                if ch == b"\\":
                    j += 2
                    continue
                if ch == b"(":
                    depth += 1
                elif ch == b")":
                    depth -= 1
                j += 1
            toks.append(("str", None))
            i = j
            continue
        if c == b"<":  # 十六进制字符串（<< 已在上面处理）
            j = data.find(b">", i)
            i = n if j < 0 else j + 1
            toks.append(("str", None))
            continue
        m = _TOKEN_NUM.match(data[i:])
        if m and m.group() not in (b"", b"-", b".", b"-."):
            toks.append(("num", float(m.group())))
            i += len(m.group())
            continue
        m = _TOKEN_OP.match(data[i:])
        if m:
            toks.append(("op", m.group().decode()))
            i += len(m.group())
            continue
        i += 1
    # 剔除内联图像 BI ... EI
    out = []
    k = 0
    while k < len(toks):
        if toks[k] == ("op", "BI"):
            j = k + 1
            while j < len(toks) and toks[j] != ("op", "EI"):
                j += 1
            k = j + 1
            continue
        out.append(toks[k])
        k += 1
    return out


def _mat_mul(m1, m2):
    """矩阵乘法 m1 × m2（PDF (a,b,c,d,e,f) 记法）。"""
    a, b, c, d, e, f = m1
    g, h, i, j, k, l = m2
    return (a * g + c * h, b * g + d * h,
            a * i + c * j, b * i + d * j,
            a * k + c * l + e, b * k + d * l + f)


def _extract_cubics(page):
    """解释页面内容流，返回全部三次贝塞尔 [(p0, c1, c2, p3)]（用户空间坐标）。

    cm 复合方向按渲染器实际语义 CTM' = CTM × M（后乘）。实测样本中
    pdfminer 的 M × CTM 顺序会把局部 cm 包裹的符号实例变换到版心之外
    （这正是门扇弧线在 pdfplumber 中丢失的原因）。
    """
    data = page.get_contents().get_data()
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack = []
    nums = []
    cur = None
    cubics = []

    def apply(m, x, y):
        a, b, c, d, e, f = m
        return (a * x + c * y + e, b * x + d * y + f)

    for typ, val in _tokenize(data):
        if typ == "num":
            nums.append(val)
            continue
        if typ != "op":
            nums = []
            continue
        op = val
        if op == "q":
            stack.append(ctm)
        elif op == "Q":
            ctm = stack.pop() if stack else ctm
        elif op == "cm" and len(nums) >= 6:
            ctm = _mat_mul(ctm, tuple(nums[-6:]))
        elif op == "m" and len(nums) >= 2:
            cur = apply(ctm, nums[-2], nums[-1])
        elif op == "l" and len(nums) >= 2:
            cur = apply(ctm, nums[-2], nums[-1])
        elif op == "c" and len(nums) >= 6 and cur:
            cubics.append((cur,
                           apply(ctm, nums[-6], nums[-5]),
                           apply(ctm, nums[-4], nums[-3]),
                           apply(ctm, nums[-2], nums[-1])))
            cur = apply(ctm, nums[-2], nums[-1])
        elif op == "v" and len(nums) >= 4 and cur:
            cubics.append((cur, cur,
                           apply(ctm, nums[-4], nums[-3]),
                           apply(ctm, nums[-2], nums[-1])))
            cur = apply(ctm, nums[-2], nums[-1])
        elif op == "y" and len(nums) >= 4 and cur:
            p = apply(ctm, nums[-2], nums[-1])
            cubics.append((cur, apply(ctm, nums[-4], nums[-3]), p, p))
            cur = p
        elif op in _PATH_END_OPS:
            cur = None
        nums = []
    return cubics


# ---------------------------------------------------------------- 圆弧判定

def _fit_circle(pts):
    """Kasa 代数圆拟合，返回 (cx, cy, r) 或 None。"""
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] ** 2 for p in pts)
    syy = sum(p[1] ** 2 for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    sz = sum(p[0] ** 2 + p[1] ** 2 for p in pts)
    sxz = sum(p[0] * (p[0] ** 2 + p[1] ** 2) for p in pts)
    syz = sum(p[1] * (p[0] ** 2 + p[1] ** 2) for p in pts)
    mat = [[sxx, sxy, sx, sxz], [sxy, syy, sy, syz], [sx, sy, n, sz]]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(mat[r][col]))
        if abs(mat[piv][col]) < 1e-9:
            return None
        mat[col], mat[piv] = mat[piv], mat[col]
        for row in range(3):
            if row != col:
                factor = mat[row][col] / mat[col][col]
                for c in range(col, 4):
                    mat[row][c] -= factor * mat[col][c]
    d0 = mat[0][3] / mat[0][0]
    e0 = mat[1][3] / mat[1][1]
    f0 = mat[2][3] / mat[2][2]
    cx, cy = d0 / 2, e0 / 2
    r2 = f0 + cx * cx + cy * cy
    if r2 <= 0:
        return None
    return cx, cy, math.sqrt(r2)


def _arc_from_cubic(p0, c1, c2, p3, resid_tol=0.10):
    """判定三次贝塞尔是否圆弧线。返回 {cx, cy, r, sweep_deg, p0, p3} 或 None。"""
    pts = []
    for j in range(8):
        t = j / 7
        mt = 1 - t
        pts.append((
            mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p3[0],
            mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p3[1],
        ))
    fit = _fit_circle(pts)
    if not fit:
        return None
    cx, cy, r = fit
    if r < 1e-6:
        return None
    resid = max(abs(math.hypot(px - cx, py - cy) - r) for px, py in pts)
    if resid / r > resid_tol:
        return None

    def ang_diff(a, b):
        return (a - b + math.pi) % (2 * math.pi) - math.pi

    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    a3 = math.atan2(p3[1] - cy, p3[0] - cx)
    am = math.atan2(pts[3][1] - cy, pts[3][0] - cx)
    sweep = ang_diff(a3, a0)
    if abs(ang_diff(am, a0)) > abs(sweep):  # 中点落在优弧侧：取另一方向
        sweep -= math.copysign(2 * math.pi, sweep)
    return {"cx": cx, "cy": cy, "r": r, "sweep_deg": math.degrees(sweep),
            "p0": p0, "p3": p3}


def extract_door_arcs(pdf_path, page_number=0,
                      radius_range_pt=(45.0, 220.0),
                      sweep_range_deg=(55.0, 135.0)):
    """提取门扇摆动弧线（pt，y 轴向上，与 pdfplumber 坐标一致）。

    Returns:
        list[dict]：每条弧含 hinge=(cx, cy)（圆心≈铰链）、radius_pt（≈门宽）、
        leaf_tip=p0（门板当前位置）、closed=p3（关闭时门扇所在墙线位置）、
        sweep_deg。无法解析（非矢量/加密/流异常）时返回空列表——调用方按
        "无弧线证据"降级处理，不报错。
    """
    try:
        reader = pypdf.PdfReader(pdf_path)
        if page_number >= len(reader.pages):
            return []
        page = reader.pages[page_number]
        rotate = int(page.get("/Rotate") or 0)
        mb = [float(v) for v in page.mediabox]
        width_mb, height_mb = mb[2] - mb[0], mb[3] - mb[1]
        cubics = _extract_cubics(page)
    except Exception:
        return []

    def to_yup(mx, my):
        # 与 pdfplumber 一致的显示坐标（y 轴向上）
        if rotate == 90:
            return (my - mb[1], mx - mb[0])
        if rotate == 270:
            return (height_mb - (my - mb[1]), mx - mb[0])
        if rotate == 180:
            return (width_mb - (mx - mb[0]), my - mb[1])
        return (mx - mb[0], height_mb - (my - mb[1]))

    arcs = []
    for p0, c1, c2, p3 in cubics:
        arc = _arc_from_cubic(p0, c1, c2, p3)
        if not arc:
            continue
        if not (radius_range_pt[0] <= arc["r"] <= radius_range_pt[1]):
            continue
        if not (sweep_range_deg[0] <= abs(arc["sweep_deg"]) <= sweep_range_deg[1]):
            continue
        arcs.append({
            "hinge": to_yup(*[arc["cx"], arc["cy"]]),
            "radius_pt": arc["r"],
            "leaf_tip": to_yup(*arc["p0"]),
            "closed": to_yup(*arc["p3"]),
            "sweep_deg": round(abs(arc["sweep_deg"]), 1),
        })

    # 去重（同一弧线常被描画两次）+ 家具整圆剔除
    uniq = []
    for arc in arcs:
        dup = False
        for kept in uniq:
            if (abs(arc["hinge"][0] - kept["hinge"][0]) < 8
                    and abs(arc["hinge"][1] - kept["hinge"][1]) < 8
                    and abs(arc["radius_pt"] - kept["radius_pt"]) < 10):
                dup = True
                break
        if not dup:
            uniq.append(arc)
    door_arcs = []
    for arc in uniq:
        # 圆心聚在一起（≈同一 fixture）且累计扫掠 ≥270° 的是圆桌/洁具整圆，
        # 不是门扇弧线（真实样本里整圆的 4 段弧拟合圆心会有几十 pt 抖动，
        # 聚类半径要比去重的 8pt 宽；双开门两铰链相距 ≈ 一个门宽、总扫掠
        # ≤180°，不会误伤）。
        siblings = [a for a in uniq
                    if math.hypot(a["hinge"][0] - arc["hinge"][0],
                                  a["hinge"][1] - arc["hinge"][1]) < 60]
        total_sweep = sum(a["sweep_deg"] for a in siblings)
        if len(siblings) >= 3 or total_sweep >= 270:
            continue
        door_arcs.append(arc)
    return door_arcs
