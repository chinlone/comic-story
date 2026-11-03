# -*- coding: utf-8 -*-
"""symbols.py — 漫画情绪符号程序化绘制（v2.10）
特点：纯程序绘制（不依赖生图模型），参数化（位置/大小/旋转/透明度/手绘抖动），
      白填充 + 黑描边与对话框同源画法，抗锯齿靠 3x 超采样。
默认只启用阳光派（心形/闪光/腮红/汗滴/惊叹/问号）；黑化派（dark 排线/dots 网点）
需显式开启 --dark 才会画。
"""
import math
import random

from PIL import Image, ImageDraw, ImageFilter

SS = 3  # 超采样倍数

SUNNY = {"sweat", "exclaim", "ask", "heart", "sparkle", "blush"}
DARK = {"dark", "dots"}
MOODY = {"anger", "tears"}          # 负面但不算黑化，需显式指定
ALL = SUNNY | DARK | MOODY

# 文案情绪 → 符号（auto 模式只用阳光派，保证默认调性）
EMOTION_RULES = [
    (("紧张", "尴尬", "有点慌", "手忙脚乱", "不好意思"), ["sweat"]),
    (("害羞", "脸红", "羞", "偷偷"), ["blush"]),
    (("开心", "喜欢", "心动", "爱你", "甜甜", "幸福", "真好", "愿", "期待"), ["heart", "sparkle"]),
    (("惊讶", "竟然", "居然", "哇", "好厉害", "太棒"), ["exclaim", "sparkle"]),
    (("？", "?", "为什么", "怎么", "是不是"), ["ask"]),
]
# 仅当 --dark 或显式指定时才启用
DARK_RULES = [
    (("生气", "气死", "忍住", "较劲", "烦"), ["anger"]),
    (("难过", "想哭", "委屈", "眼泪"), ["tears"]),
    (("黑化", "emo", "丧", "崩溃", "疲惫", "沉重", "低气压"), ["dark", "dots"]),
]


def _bez(p0, p1, p2, p3, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        out.append((
            mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
        ))
    return out


def _jitter(pts, amp, seed=0, freq=6.0):
    """手绘微抖：沿法向低频扰动，端点扰动线性收敛到 0（接缝不裂）"""
    if amp <= 0 or len(pts) < 3:
        return pts
    rnd = random.Random(seed)
    ph = rnd.uniform(0, 6.283)
    n = len(pts)
    out = []
    for i, (x, y) in enumerate(pts):
        t = i / max(1, n - 1)
        env = math.sin(math.pi * t)                      # 两端归零
        d = (math.sin(t * freq + ph) * 0.7 + rnd.uniform(-0.3, 0.3)) * amp * env
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1
        out.append((x + (-dy / L) * d, y + (dx / L) * d))
    return out


def _stroke_shape(d, pts, border, fill="white", jit=1.2, seed=0):
    p = _jitter(pts, jit, seed)
    d.polygon(p, fill=fill)
    d.line(p + [p[0]], fill="black", width=border, joint="curve")


def _drop_pts(cx, cy, r, tip=1.9):
    pts = []
    n = 40
    for i in range(n + 1):                                # 上半圆
        th = math.pi + math.pi * i / n
        pts.append((cx + r * math.cos(th), cy + r * math.sin(th)))
    pts += _bez((cx + r, cy), (cx + r * 0.96, cy + r * 0.8),
                (cx + r * 0.38, cy + r * (tip - 0.3)), (cx, cy + r * tip), 14)
    pts += _bez((cx, cy + r * tip), (cx - r * 0.38, cy + r * (tip - 0.3)),
                (cx - r * 0.96, cy + r * 0.8), (cx - r, cy), 14)
    return pts


# ---------------- 各符号绘制（局部坐标系：中心 0,0；单位 = s）----------------
def _s_sweat(d, s, seed):
    r = s * 0.52
    pts = _drop_pts(0, -s * 0.15, r)
    _stroke_shape(d, pts, max(3, int(s * 0.10)), seed=seed)
    d.polygon(_jitter([(-r * 0.15, -s * 0.30), (-r * 0.55, -s * 0.05),
                       (-r * 0.30, -s * 0.02), (-r * 0.02, -s * 0.22)], 0.4, seed + 1), fill="white")


def _s_tears(d, s, seed):
    for k, (dx, dy, sc) in enumerate([(-s * 0.42, -s * 0.22, 0.62), (s * 0.34, s * 0.34, 0.44)]):
        r = s * 0.52 * sc
        pts = _drop_pts(dx, dy, r)
        _stroke_shape(d, pts, max(2, int(s * 0.10 * sc)), seed=seed + k)
        d.polygon(_jitter([(dx - r * 0.15, dy + r * 0.05), (dx - r * 0.5, dy + r * 0.35),
                           (dx - r * 0.2, dy + r * 0.4), (dx + r * 0.02, dy + r * 0.2)],
                          0.3, seed + 5 + k), fill="white")


def _s_anger(d, s, seed):
    # 日漫"青筋"：4 个外凸折角 + 中心短轴，组成米字骨架（v2.10 定稿）
    for k in range(4):
        a = math.radians(45 + 90 * k)
        tip = (math.cos(a) * s * 0.95, math.sin(a) * s * 0.95)
        core = (math.cos(a) * s * 0.30, math.sin(a) * s * 0.30)
        segs = [[tip, core]]
        for sgn in (1, -1):
            aa = a + sgn * math.radians(150)
            segs.append([tip, (tip[0] + math.cos(aa) * s * 0.50,
                               tip[1] + math.sin(aa) * s * 0.50)])
        for seg in segs:
            d.line(seg, fill="white", width=max(4, int(s * 0.26)), joint="curve")
            d.line(seg, fill="black", width=max(3, int(s * 0.16)), joint="curve")
        for sg in (1, -1):
            aa = a + sg * math.radians(150)
            d.ellipse([seg[1][0] - s * 0.08, seg[1][1] - s * 0.08,
                       seg[1][0] + s * 0.08, seg[1][1] + s * 0.08], fill="black")
def _s_exclaim(d, s, seed):
    h, w = s * 1.55, s * 0.20
    pts = _bez((-w, -h * 0.5), (-w * 1.1, -h * 0.1), (-w * 0.7, h * 0.12), (-w * 0.25, h * 0.16), 10)
    pts += _bez((w * 0.2, h * 0.17), (w * 0.75, h * 0.15), (w * 1.05, -h * 0.12), (w * 1.0, -h * 0.5), 10)
    pts += _bez((w * 0.6, -h * 0.52), (0, -h * 0.56), (-w * 0.6, -h * 0.53), (-w, -h * 0.5), 8)
    _stroke_shape(d, pts, max(3, int(s * 0.10)), jit=1.0, seed=seed)
    r = s * 0.17
    cy = h * 0.40
    d.ellipse([-r, cy - r * 0.9, r, cy + r * 1.1], fill="white", outline="black",
              width=max(3, int(s * 0.10)))


def _s_ask(d, s, seed):
    h = s * 0.9
    pts = []
    # 问号钩
    for i in range(26):
        t = math.pi * 1.05 * i / 25
        x = math.cos(t - math.pi * 1.5) * h * 0.52
        y = math.sin(t - math.pi * 1.5) * h * 0.36 + h * 0.2
        pts.append((x * 0.3 + math.sin(t) * h * 0.42, -h * 0.25 + y * 0.4))
    pts += _bez((h * 0.30, h * 0.30), (0, h * 0.12), (0, h * 0.2), (0, h * 0.45), 10)
    d.line(pts, fill="white", width=max(6, int(s * 0.30)), joint="curve")
    d.line(pts, fill="black", width=max(4, int(s * 0.18)), joint="curve")
    r = s * 0.16
    d.ellipse([-r, s * 0.80 - r, r, s * 0.80 + r], fill="white", outline="black",
              width=max(3, int(s * 0.10)))


def _s_heart(d, s, seed):
    pts = []
    for i in range(110):
        t = 2 * math.pi * i / 109
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x * s / 17.5, -y * s / 17.5))
    _stroke_shape(d, pts, max(3, int(s * 0.09)), fill=(255, 136, 168, 255), jit=0.9, seed=seed)
    # 高光收进左瓣内侧，避免压到轮廓形成缺口（v2.10 修）
    d.polygon([(-s * 0.40, -s * 0.24), (-s * 0.24, -s * 0.34),
               (-s * 0.18, -s * 0.18), (-s * 0.34, -s * 0.10)], fill="white")


def _s_sparkle(d, s, seed):
    pts = []
    for i in range(8):
        a = math.pi / 4 * i - math.pi / 2
        r = s * (1.0 if i % 2 == 0 else 0.15)
        pts.append((math.cos(a) * r, math.sin(a) * r))
    _stroke_shape(d, pts, max(2, int(s * 0.07)), fill=(255, 243, 150, 255), jit=0.6, seed=seed)
    # 星芒内的细光不画黑线（会显错位），改为外圈两颗小星点（v2.10 修）
    for ang, rr in ((math.radians(35), s * 1.25), (math.radians(215), s * 1.05)):
        px, py = math.cos(ang) * rr, math.sin(ang) * rr
        sz = s * 0.16
        d.polygon([(px, py - sz), (px + sz * 0.35, py), (px, py + sz), (px - sz * 0.35, py)],
                  fill="white", outline="black")


def _s_blush(d, s, seed):
    rnd = random.Random(seed)
    for i in range(4):
        x = -s * 0.72 + s * 1.44 * i / 3
        k = 1.0 - 0.15 * abs(i - 1.5) / 1.5
        tilt = rnd.uniform(-0.10, 0.10)
        d.line([(x - s * 0.13, s * 0.22 * k), (x + s * 0.13 + tilt * s, -s * 0.22 * k)],
               fill=(240, 126, 150, 232), width=max(3, int(s * 0.13)))


def _s_dark(d, s, seed):
    # 手绘排线：中间最长、边缘渐短，倾斜与粗细随机（v2.10 收边，不出界）
    rnd = random.Random(seed)
    x = -s * 0.90
    while x < s * 0.90:
        edge = 1 - abs(x / (s * 0.90))
        top = -s * (0.45 + 0.50 * edge)
        bot = s * (0.30 + 0.60 * edge) * rnd.uniform(0.75, 1.0)
        d.line([(x, top), (x + rnd.uniform(0.03, 0.09) * s, bot)],
               fill=(24, 24, 24, 232), width=max(2, int(rnd.uniform(0.05, 0.085) * s)))
        x += rnd.uniform(0.085, 0.15) * s


def _s_dots(d, s, seed):
    step = 0.16 * s
    yy = -s
    while yy < s:
        xx = -s
        while xx < s:
            dd = math.hypot(xx, yy)
            if dd < s:
                rr = 0.045 * s * (1 - 0.5 * dd / s)
                d.ellipse([xx - rr, yy - rr, xx + rr, yy + rr], fill=(36, 36, 36, 236))
            xx += step
        yy += step


_PAINTERS = {
    "sweat": _s_sweat, "tears": _s_tears, "anger": _s_anger, "exclaim": _s_exclaim,
    "ask": _s_ask, "heart": _s_heart, "sparkle": _s_sparkle, "blush": _s_blush,
    "dark": _s_dark, "dots": _s_dots,
}


def _render_glyph(ch, size, frac=0.78, stroke_frac=0.085):
    """用字体字形做 mask 再套白描边——标准字形 100% 不走形（问号用这条）"""
    from PIL import ImageFont
    big = size * SS
    f = ImageFont.truetype("/usr/local/share/fonts/custom/NotoSansSC-Bold.ttf", int(big * frac))
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).text((big / 2, big / 2), ch, font=f, fill=255, anchor="mm")
    k = max(1, int(big * stroke_frac))
    kk = k * 2 + 1
    outer = m.filter(ImageFilter.MaxFilter(kk))
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    w = Image.new("RGBA", (big, big), (255, 255, 255, 255))
    w.putalpha(outer)
    b = Image.new("RGBA", (big, big), (0, 0, 0, 255))
    b.putalpha(m)
    layer.alpha_composite(w)
    layer.alpha_composite(b)
    return layer.resize((size, size), Image.LANCZOS)


def render(name, size, seed=0):
    """渲染单个符号 → 尺寸 size×size 的 RGBA（已抗锯齿）"""
    if name == "ask":
        return _render_glyph("？", size)
    if name == "exclaim":
        return _render_glyph("！", size)
    if name not in _PAINTERS:
        raise KeyError("unknown symbol: %s (可选: %s)" % (name, ",".join(sorted(ALL))))
    big = size * SS
    cell = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(cell)
    d._image = cell  # 兼容统一接口
    # 缩放坐标系：把 s 定为 size*0.5（原语以 s 为单位绘制，占 2s）
    s = big * 0.5
    _PAINTERS[name](_Scaler(d, big, s), s, seed)
    if name in ("dark", "dots"):
        a = cell.split()[3].filter(ImageFilter.GaussianBlur(SS * 0.6))
        cell.putalpha(a)
    return cell.resize((size, size), Image.LANCZOS)


class _Scaler:
    """把以 (0,0) 为中心的坐标平移到画布中心"""

    def __init__(self, draw, big, s):
        self._d = draw
        self.c = big / 2.0
        self.big = big
        self.s = s

    def _t(self, pts):
        return [(x + self.c, y + self.c) for x, y in pts]

    def polygon(self, pts, **kw):
        self._d.polygon(self._t(pts), **kw)

    def line(self, pts, **kw):
        self._d.line(self._t(pts), **kw)

    def ellipse(self, box, **kw):
        x0, y0, x1, y1 = box
        self._d.ellipse([x0 + self.c, y0 + self.c, x1 + self.c, y1 + self.c], **kw)


def draw_symbol(base, name, cx, cy, size, rot=0.0, alpha=255, seed=0):
    """在 base(RGBA) 上画一个符号，中心 (cx,cy)，直径 size，可旋转/调透明度。
    返回符号的 bbox（像素）。"""
    cell = render(name, int(size), seed)
    if abs(rot) > 0.05:
        cell = cell.rotate(-rot, resample=Image.BICUBIC)
    if alpha < 255:
        a = cell.split()[3].point(lambda v: int(v * alpha / 255.0))
        cell.putalpha(a)
    x = int(cx - cell.width / 2)
    y = int(cy - cell.height / 2)
    base.alpha_composite(cell, (x, y)) if base.mode == "RGBA" else base.paste(cell, (x, y), cell)
    return (x, y, x + cell.width, y + cell.height)


def pick_for_text(text, scene="people", allow_dark=False):
    """按文案情绪挑符号（auto 模式：默认阳光派；黑化派需 allow_dark）"""
    text = text or ""
    rules = list(EMOTION_RULES) + (DARK_RULES if allow_dark else [])
    for keys, syms in rules:
        if any(k in text for k in keys):
            if not allow_dark:
                syms = [s for s in syms if s in SUNNY]
            if syms:
                return list(syms)
    return []


# ---------------- 自动摆位 ----------------
SIZE_RATIO = {
    "sweat": 0.085, "tears": 0.100, "anger": 0.095, "exclaim": 0.105, "ask": 0.105,
    "heart": 0.095, "sparkle": 0.105, "blush": 0.155, "dark": 0.300, "dots": 0.260,
}

# 候选位（以脸中心为原点，单位=脸半宽/半高）：先右上/左上，再两侧，最后更远
_CANDS = [(1.30, -1.00), (-1.30, -1.00), (1.62, -0.10), (-1.62, -0.10),
          (0.85, -1.35), (-0.85, -1.35), (1.95, -1.60), (-1.95, -1.60),
          (0.00, -1.60), (1.85, 0.95), (-1.85, 0.95), (2.20, 0.10), (-2.20, 0.10),
          (1.45, 0.55), (-1.45, 0.55), (0.55, -1.75), (-0.55, -1.75)]


def _ov(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def place_layer(size, names, face=None, avoid=None, seed=0):
    """按"靠近人物头部但不压脸/不压框/不出画布"自动摆符号，返回 (layer, bboxes)。
    dark/dots 是背景阴影，允许压人物（不参与脸的排斥）。"""
    W, H = size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rnd = random.Random(int(seed) * 131 + 7)
    avoid = [b for b in (avoid or []) if b]
    if face and all(face):
        fx0, fy0, fx1, fy1 = face
        fcx, fcy = (fx0 + fx1) / 2.0, (fy0 + fy1) / 2.0
        fw, fh = max(2, fx1 - fx0), max(2, fy1 - fy0)
        face_ok = True
    else:
        fcx, fcy = W * 0.5, H * 0.30
        fw, fh = W * 0.30, H * 0.24
        fx0 = fy0 = fx1 = fy1 = 0
        face_ok = False
    placed = []
    for i, name in enumerate(names):
        sp = int(min(W, H) * SIZE_RATIO.get(name, 0.10) * (1.0 if i == 0 else 0.72))
        order = _CANDS[:]
        rnd.shuffle(order)
        background = name in DARK
        ok = False
        for relax in (0, 1):
            if ok:
                break
            for dx, dy in order:
                cx, cy = fcx + dx * fw * 0.5, fcy + dy * fh * 0.5
                r = sp / 2.0
                box = (cx - r, cy - r, cx + r, cy + r)
                mg = sp * (0.12 if relax == 0 else 0.04)
                if box[0] < W * 0.015 or box[1] < H * 0.015 or box[2] > W * 0.985 or box[3] > H * 0.985:
                    continue
                if face_ok and (not background) and _ov(box, (fx0 - mg, fy0 - mg, fx1 + mg, fy1 + mg)):
                    continue
                if any(_ov(box, (b[0] - mg, b[1] - mg, b[2] + mg, b[3] + mg)) for b in avoid):
                    continue
                if any(_ov(box, (p[0] - mg, p[1] - mg, p[2] + mg, p[3] + mg)) for p in placed):
                    continue
                rot = rnd.uniform(-16, 16)
                bb = draw_symbol(layer, name, cx, cy, sp, rot=rot, seed=rnd.randrange(999))
                placed.append(bb)
                ok = True
                break
    return layer, placed
