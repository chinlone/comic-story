#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_text.py v3.1 — 漫画风配文叠加（对话框形状库，按场景自动选风格）。

形状（全收，详见 SKILL.md）：
  ellipse 椭圆(正常说话) | rounded 圆角矩形(平静/旁白) | circle 正圆(俏皮)
  petal 云朵花瓣(活泼) | trumpet 梯形喇叭(喊话) | quad 不规则四边形(随性)
  burst 爆炸星形(大喊/拟声) | thought 思考云朵(内心独白) | wave 颤抖波浪(害怕)
  double 双层强调框(粗外+细内黑) | mini 迷你小气泡 | freehand 自由异形
  whisper 虚线低语框 | caption 旁白矩形框(无尾) | shoujo 少女圆润(柔和)
笔触基调 --bubble-tone:
  shonen 硬朗手绘(线宽较粗+有机微抖) | shoujo 柔和圆润(均匀细线)
  auto 由调用方按场景决定（脚本内映射 shonen）
对话框形态严格对齐提示词生成的样式：细尖直尾(根部窄/尖端锐/近直线微弯)、
气泡轮廓手绘有机微抖。全部白底黑边（double=粗外+细内黑），无阴影、无半调点。
多行文字：自动换行并撑大气泡，不溢出。
不挡脸：默认放四角留白区；--bubble-xy 手动归一化坐标精确规避人脸。
依赖 Pillow，中文字体 Noto Sans SC（已验证存在）。
"""
import argparse
import math
import os
import random
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageColor, ImageFilter, ImageChops

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TITLE_FONT = "/usr/local/share/fonts/custom/NotoSansSC-Bold.ttf"  # 粗印刷体（拟声词/标题）
DEFAULT_TEXT_FONT = os.path.join(_SKILL_DIR, "fonts", "ZCOOLKuaiLe.ttf")  # 圆润手写体（对话框，打包进技能 fonts/）

_BUBBLE_TEXT = "#2B2B2B"

# v2.9.10：ZCOOL 快乐体缺 ·℃①→★ 等 588 个 GB2312 符号，用打包的子集字体兜底补画，
# 避免出现 ☒ 方块（该子集来自 NotoSansSC，OFL 免费商用，仅 195KB）
_FALLBACK_FONT_PATH = os.path.join(_SKILL_DIR, "fonts", "fallback_cjk.ttf")
_MISSING_PATH = os.path.join(_SKILL_DIR, "fonts", "zcool_missing.txt")
_MISSING_CHARS = None
_FB_CACHE = {}


def _missing_chars():
    global _MISSING_CHARS
    if _MISSING_CHARS is None:
        try:
            with open(_MISSING_PATH, "r", encoding="utf-8") as f:
                _MISSING_CHARS = set(f.read())
        except Exception:
            _MISSING_CHARS = set()
    return _MISSING_CHARS


def _fallback_font(size):
    f = _FB_CACHE.get(size)
    if f is None:
        f = load_font(_FALLBACK_FONT_PATH, size)
        _FB_CACHE[size] = f
    return f


def _need_fallback(text):
    miss = _missing_chars()
    if not miss:
        return False
    return any((ch in miss and not ch.isspace()) for ch in text)


def draw_mixed_text(draw, cx, cy, text, font, fill="#2B2B2B",
                    stroke_width=0, stroke_fill=None):
    """按字符选字体绘制：主字体没有的符号用 fallback 子集字体补上（不出方块）。
    无缺字时直接走原生 draw.text，零开销。"""
    if not _need_fallback(text):
        draw.text((cx, cy), text, font=font, fill=fill, anchor="mm",
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        return
    miss = _missing_chars()
    fb = _fallback_font(font.size)
    widths = []
    for ch in text:
        f = fb if (ch in miss and not ch.isspace()) else font
        widths.append(draw.textlength(ch, font=f))
    total = sum(widths)
    x = cx - total / 2.0
    for ch, w in zip(text, widths):
        f = fb if (ch in miss and not ch.isspace()) else font
        draw.text((x, cy), ch, font=f, fill=fill, anchor="lm",
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        x += w


def load_font(path, size, index=0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception as e:
        sys.exit("[render_text] 字体加载失败: %s\n%s" % (path, e))


def wrap_text(draw, text, font, max_width):
    lines = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            test = line + ch
            if draw.textlength(test, font=font) <= max_width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = ch
        lines.append(line)
    # v2.12.1：避免末行只剩 1 个字（或只剩标点"~"）形成"孤字行"
    if len(lines) >= 2 and len(lines[-1]) <= 1 and len(lines[-2]) >= 3:
        _mv = lines[-2][-1]
        if draw.textlength(_mv + lines[-1], font=font) <= max_width * 1.15:
            lines[-2] = lines[-2][:-1]
            lines[-1] = _mv + lines[-1]
    return lines


def tail_polygon(cx, cy, bw, bh, direction, curve=0.10, jitter=0.0, seed=0, root_ratio=0.065):
    """细尖尾（对齐提示词生成的 pointed tail）：根部窄(≈线宽2-3倍)、尖端锐、
    中轴近直线微弯，可选手绘微抖；非粗弯柄。"""
    conf = {
        "bl": (cx - bw * 0.10, cy + bh * 0.28, cx - bw * 0.30, cy + bh * 0.5 + bh * 0.40),
        "br": (cx + bw * 0.10, cy + bh * 0.28, cx + bw * 0.30, cy + bh * 0.5 + bh * 0.40),
        "tl": (cx - bw * 0.10, cy - bh * 0.28, cx - bw * 0.30, cy - bh * 0.5 - bh * 0.40),
        "tr": (cx + bw * 0.10, cy - bh * 0.28, cx + bw * 0.30, cy - bh * 0.5 - bh * 0.40),
        "bottom": (cx, cy + bh * 0.28, cx, cy + bh * 0.5 + bh * 0.42),
        "left": (cx - bw * 0.28, cy, cx - bw * 0.5 - bh * 0.40, cy),
        "right": (cx + bw * 0.28, cy, cx + bw * 0.5 + bh * 0.40, cy),
        "top": (cx, cy - bh * 0.28, cx, cy - bh * 0.5 - bh * 0.42),
    }
    if direction in conf:
        rx, ry, tx, ty = conf[direction]
    else:
        # v2.9.9：任意角度尾巴——按方向在椭圆上的投影推根部与尖端
        th = _tail_dir_theta(direction)
        c, s = math.cos(th), math.sin(th)
        rx = cx + bw * 0.28 * c
        ry = cy + bh * 0.28 * s
        L = bw * 0.22 * abs(c) + bh * 0.40 * abs(s) + 0.08 * min(bw, bh)
        tx = rx + L * c
        ty = ry + L * s
    dx = tx - rx
    dy = ty - ry
    L = math.hypot(dx, dy) or 1
    nx0, ny0 = -dy / L, dx / L
    mx, my = (rx + tx) / 2, (ry + ty) / 2
    px = mx + nx0 * L * curve
    py = my + ny0 * L * curve
    root_w = max(6, bw * root_ratio)
    steps = 16
    random.seed(seed)
    pts = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        bx = mt ** 2 * rx + 2 * mt * t * px + t ** 2 * tx
        by = mt ** 2 * ry + 2 * mt * t * py + t ** 2 * ty
        ddx = 2 * mt * (px - rx) + 2 * t * (tx - px)
        ddy = 2 * mt * (py - ry) + 2 * t * (ty - py)
        tl = math.hypot(ddx, ddy) or 1
        nx2, ny2 = -ddy / tl, ddx / tl
        w = root_w * (1 - t) ** 1.3 + 0.5  # 根部窄→尖端近锐
        jx = random.uniform(-jitter, jitter)
        jy = random.uniform(-jitter, jitter)
        pts.append((bx, by, nx2, ny2, w, jx, jy))
    left = [(p[0] + p[2] * p[4] + p[5], p[1] + p[3] * p[4] + p[6]) for p in pts]
    right = [(p[0] - p[2] * p[4] + p[5], p[1] - p[3] * p[4] + p[6]) for p in pts]
    return left + right[::-1]


def _tail_dir_theta(direction):
    # v2.9.9：支持 "deg:23.5" 形式的角度尾巴（斜向化用）
    if isinstance(direction, str) and direction.startswith("deg:"):
        return math.radians(float(direction[4:]))
    return {
        "right": 0.0, "bottom": math.pi / 2, "left": math.pi,
        "top": -math.pi / 2, "br": math.radians(50), "bl": math.radians(130),
        "tr": -math.pi / 4, "tl": -math.pi * 3 / 4,
    }[direction]


_BASE_DEG = {"right": 0.0, "bottom": 90.0, "left": 180.0, "top": -90.0}


def skew_direction(direction, seed=0, lo=15.0, hi=26.0):
    """v2.9.9：把端正的四向尾巴（上/下/左/右）改成带倾角的方向，避免"太正"不好看。
    已是斜向(br/bl/tr/tl)或 none 的原样返回；返回 "deg:xx" 形式的确定角度（同 seed 稳定）。"""
    if not direction or direction == "none" or str(direction).startswith("deg:"):
        return direction
    if direction not in _BASE_DEG:
        return direction
    rnd = random.Random(int(seed) * 7919 + 23)
    if direction in ("top", "bottom"):
        lo, hi = max(lo, 17.0), max(hi, 29.0)   # 垂直方向视觉更"正"，偏角需更大才不呆板
    mag = rnd.uniform(lo, hi)
    sign = 1.0 if rnd.random() < 0.5 else -1.0
    return "deg:%.1f" % (_BASE_DEG[direction] + sign * mag)


def _jitter_val(x, y, seed):
    """基于位置的低频长波手绘噪声(~[-1,1])：相邻点缓变 → 线顺滑连续，仅隐约手绘。"""
    return (math.sin(x * 0.018 + seed * 1.7) * 0.55
            + math.sin(y * 0.022 + seed * 2.3) * 0.30
            + math.sin((x + y) * 0.015 + seed * 0.9) * 0.15)


def _offset_polygon(pts, width):
    """中心线 → 等宽描边填充多边形（备用，主流程改用语义学描边）。"""
    n = len(pts)
    w2 = width / 2
    left, right = [], []
    for i in range(n):
        x0, y0 = pts[i]
        xm, ym = pts[(i - 1) % n]
        xp, yp = pts[(i + 1) % n]
        dx, dy = xp - xm, yp - ym
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L, dx / L
        left.append((x0 + nx * w2, y0 + ny * w2))
        right.append((x0 - nx * w2, y0 - ny * w2))
    return left + right[::-1]


def _stroke(draw, pts, width, fill="black"):
    draw.polygon(_offset_polygon(pts, width), fill=fill)


def _quad(p0, p1, p2, t):
    mt = 1 - t
    return (mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
            mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1])


def _tail_silhouette(a, b, t):
    """尾巴白色剪影多边形：两侧向外微凸(根部圆润) + 尖端锐尖。"""
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    dx, dy = t[0] - mid[0], t[1] - mid[1]
    L = math.hypot(dx, dy) or 1
    px, py = -dy / L, dx / L
    bow = 0.14 * L
    c1 = ((a[0] + t[0]) / 2 + px * bow, (a[1] + t[1]) / 2 + py * bow)
    c2 = ((b[0] + t[0]) / 2 + px * bow, (b[1] + t[1]) / 2 + py * bow)
    pts = []
    N = 14
    for i in range(N + 1):
        pts.append(_quad(a, c1, t, i / N))
    for i in range(1, N + 1):
        pts.append(_quad(t, c2, b, i / N))
    return pts


def _paint_bubble(img, cx, cy, rx, ry, tail, border, S=2,
                  fill_interior=True, body="ellipse", radius=42):
    """形态学描边：先填白色剪影(主体+尾巴合并)，再膨胀-腐蚀出均匀连续黑边。
    仅在气泡局部包围盒内运算（不扫全图），保证性能与连续干净一根线、锐尖。"""
    W, H = img.size
    tlen = max(rx, ry) * 0.62 if (tail and tail != "none") else 0  # v2.9.9 斜向尾巴取保守 margin
    m = int(border * 2 + tlen + 40)
    x0 = max(0, int(cx - rx - m)); y0 = max(0, int(cy - ry - m))
    x1 = min(W, int(cx + rx + m)); y1 = min(H, int(cy + ry + m))
    cw, ch = x1 - x0, y1 - y0
    if cw <= 0 or ch <= 0:
        return
    local = Image.new("L", (cw * S, ch * S), 0)
    bd = ImageDraw.Draw(local)
    lcx, lcy = (cx - x0) * S, (cy - y0) * S
    if body == "rounded":
        bd.rounded_rectangle([lcx - rx * S, lcy - ry * S, lcx + rx * S, lcy + ry * S],
                             radius=radius * S, fill=255)
    else:
        bd.ellipse([lcx - rx * S, lcy - ry * S, lcx + rx * S, lcy + ry * S], fill=255)
    if tail and tail != "none":
        a, b, t, _, _, _ = _tail_geometry(cx, cy, rx, ry, tail, border)
        sil = [((x - x0) * S, (y - y0) * S) for (x, y) in _tail_silhouette(a, b, t)]
        bd.polygon(sil, fill=255)
    mask = np.array(local)
    k = max(1, int(round(border * S / 2)))
    kk = 2 * k + 1
    dil = np.array(Image.fromarray(mask).filter(ImageFilter.MaxFilter(kk)))
    ero = np.array(ImageChops.invert(
        ImageChops.invert(Image.fromarray(mask)).filter(ImageFilter.MaxFilter(kk))))
    if fill_interior:
        alpha = dil.astype(np.uint8)
        col = np.where(ero > 0, 255, 0).astype(np.uint8)
    else:
        ring = (dil > 0) & (ero == 0)
        alpha = ring.astype(np.uint8) * 255
        col = np.zeros_like(ero, dtype=np.uint8)
    rgba = np.dstack([col, col, col, alpha])
    res = Image.fromarray(rgba, "RGBA").resize((cw, ch), Image.LANCZOS)
    img.paste(res, (x0, y0), res)


def _paint_polygon_bubble(draw, body_pts, tail_pts, border, S=2):
    """通用形态学连续描边：任意主体多边形 + 尾巴多边形 合并成一个白色剪影，
    再膨胀-腐蚀出均匀连续黑边（一条线、根部无封边、尖角不断）。
    让 petal/wave/quad/freehand/trumpet 等带尾形状学到 ellipse 的'一体无封边'正确画法。"""
    img = draw._image
    W, H = img.size
    pts = list(body_pts) + (list(tail_pts) if tail_pts else [])
    if not pts:
        return
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    m = int(border * 2 + 20)
    x0 = max(0, int(min(xs) - m))
    y0 = max(0, int(min(ys) - m))
    x1 = min(W, int(max(xs) + m))
    y1 = min(H, int(max(ys) + m))
    cw, ch = x1 - x0, y1 - y0
    if cw <= 0 or ch <= 0:
        return
    local = Image.new("L", (cw * S, ch * S), 0)
    bd = ImageDraw.Draw(local)

    def tf(p):
        return ((p[0] - x0) * S, (p[1] - y0) * S)

    bd.polygon([tf(p) for p in body_pts], fill=255)
    if tail_pts:
        bd.polygon([tf(p) for p in tail_pts], fill=255)
    mask = np.array(local)
    k = max(1, int(round(border * S / 2)))
    kk = 2 * k + 1
    dil = np.array(Image.fromarray(mask).filter(ImageFilter.MaxFilter(kk)))
    ero = np.array(ImageChops.invert(ImageChops.invert(Image.fromarray(mask)).filter(ImageFilter.MaxFilter(kk))))
    alpha = dil.astype(np.uint8)
    col = np.where(ero > 0, 255, 0).astype(np.uint8)
    rgba = np.dstack([col, col, col, alpha])
    res = Image.fromarray(rgba, "RGBA").resize((cw, ch), Image.LANCZOS)
    img.paste(res, (x0, y0), res)


def _radial(cx, cy, rx, ry, theta):
    c = math.cos(theta); s = math.sin(theta)
    R = (rx * ry) / math.sqrt((ry * c) ** 2 + (rx * s) ** 2)
    return (cx + R * c, cy + R * s)


def _tail_geometry(cx, cy, rx, ry, direction, border):
    """计算尾巴根部A/B(在气泡轮廓上)、尖端T、中轴法向、根部宽度。"""
    theta = _tail_dir_theta(direction)
    ro = _radial(cx, cy, rx, ry, theta)
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    Rr = (rx * ry) / math.sqrt((ry * math.cos(theta)) ** 2 + (rx * math.sin(theta)) ** 2)
    root_w = max(border * 2.8, 10)          # 根部窄(≈线宽2-3倍)，无宽大领口
    delta = min(root_w / (2 * Rr), 0.6)     # 小角 → A-B 弦≈root_w
    a = _radial(cx, cy, rx, ry, theta - delta)
    b = _radial(cx, cy, rx, ry, theta + delta)
    horiz = direction in ("left", "right")
    _c, _s = abs(math.cos(theta)), abs(math.sin(theta))
    tail_len = (rx * _c + ry * _s) * 0.46   # v2.9.9 斜向尾巴按方向投影取长（四向旧行为不变）
    t = (ro[0] + dx * tail_len, ro[1] + dy * tail_len)
    return a, b, t, (dx, dy), (nx, ny), root_w


def _tail_side(p0, p1, nx, ny, bend, jitter, seed):
    """一条手绘微抖的侧边(二次贝塞尔+随机噪声)，从根部点平滑弯到尖端。"""
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    ctrlx, ctrly = mx + nx * bend, my + ny * bend
    N = 22
    pts = []
    random.seed(seed)
    for i in range(N + 1):
        t = i / N; mt = 1 - t
        x = mt * mt * p0[0] + 2 * mt * t * ctrlx + t * t * p1[0]
        y = mt * mt * p0[1] + 2 * mt * t * ctrly + t * t * p1[1]
        if jitter > 0:
            jv = _jitter_val(x, y, seed)
            x += jv * jitter
            y += jv * jitter * 0.8
        pts.append((x, y))
    return pts


def _angle_diff(a, b):
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def merged_bubble_outline(cx, cy, rx, ry, direction, border, jitter=0.0, seed=0):
    """气泡(椭圆) + 尾巴 = 一条连续闭合轮廓：尾巴是轮廓上的平滑尖凸
    (沿角度向外推尖峰，根部导数归零 → 与气泡 C1 连续，零折角、圆润)。"""
    theta = _tail_dir_theta(direction)
    horiz = direction in ("left", "right")
    _c, _s = abs(math.cos(theta)), abs(math.sin(theta))
    tail_len = (rx * _c + ry * _s) * 0.50              # v2.9.9 斜向尾巴按投影取长
    Rr = (rx * ry) / math.sqrt((ry * math.cos(theta)) ** 2 + (rx * math.sin(theta)) ** 2)
    w = 2 * math.asin(min(border * 2.6, Rr * 0.18) / (2 * Rr))  # 根部窄细(≈线宽2.6倍)
    w = max(w, 0.12)
    M = 360                                           # 高密度 → 尖更平滑
    pts = []
    for i in range(M + 1):
        th = 2 * math.pi * i / M
        x = cx + rx * math.cos(th)
        y = cy + ry * math.sin(th)
        d = _angle_diff(th, theta)
        if abs(d) < w:                                # 仅在尾巴角窗内向外推尖
            u = abs(d) / w
            extra = tail_len * (1 - u) ** 3.0         # 中心锐尖、边缘平滑归零
            ex, ey = rx * math.cos(th), ry * math.sin(th)
            en = math.hypot(ex, ey) or 1
            x += ex / en * extra
            y += ey / en * extra
        if jitter > 0:
            jv = _jitter_val(x, y, seed)
            x += jv * jitter
            y += jv * jitter * 0.8
        pts.append((x, y))
    return pts


def draw_tail_fused(draw, cx, cy, rx, ry, direction, border, jitter=0.0, seed=0):
    """矩形类主体已画(白底黑边)后融合尾巴：白底盖住根部段 + 描两侧平滑尖边，无横切黑块。"""
    theta = _tail_dir_theta(direction)
    c, s = math.cos(theta), math.sin(theta)
    tc = (rx / abs(c)) if abs(c) > 1e-6 else 1e9
    ts = (ry / abs(s)) if abs(s) > 1e-6 else 1e9
    tt = min(tc, ts)
    rox, roy = cx + c * tt, cy + s * tt          # 矩形边界上沿方向的最远点
    nx, ny = -s, c
    root_w = max(border * 2.8, 10)
    a = (rox - nx * root_w / 2, roy - ny * root_w / 2)
    b = (rox + nx * root_w / 2, roy + ny * root_w / 2)
    horiz = direction in ("left", "right")
    tail_len = (rx if horiz else ry) * 0.30
    T = (rox + c * tail_len, roy + s * tail_len)
    bend = 0.10 * math.hypot(T[0] - (a[0] + b[0]) / 2, T[1] - (a[1] + b[1]) / 2)
    jit = jitter if jitter > 0 else 0.0
    side_a = _tail_side(a, T, nx, ny, bend, jit, seed)
    side_b = _tail_side(b, T, nx, ny, bend, jit, seed + 3)
    draw.polygon(side_a + side_b[::-1], fill="white", outline=None)   # 盖住根部矩形黑边
    draw.line(side_a, fill="black", width=border, joint="curve")
    draw.line(side_b, fill="black", width=border, joint="curve")


def petal_points(cx, cy, rw, rh, lobes=7, amp=0.13, jitter=0.0, seed=0):
    random.seed(seed)
    pts = []
    n = 140
    for i in range(n):
        th = 2 * math.pi * i / n
        r = 1 + amp * math.sin(lobes * th)
        jx = random.uniform(-jitter, jitter)
        jy = random.uniform(-jitter, jitter)
        pts.append((cx + math.cos(th) * rw * r + jx, cy + math.sin(th) * rh * r + jy))
    return pts


def wave_points(cx, cy, rw, rh, amp=0.05, freq=22, jitter=0.0, seed=0):
    random.seed(seed)
    pts = []
    n = 200
    for i in range(n):
        th = 2 * math.pi * i / n
        r = 1 + amp * math.sin(freq * th)
        jx = random.uniform(-jitter, jitter)
        jy = random.uniform(-jitter, jitter)
        pts.append((cx + math.cos(th) * rw * r + jx, cy + math.sin(th) * rh * r + jy))
    return pts


def burst_points(cx, cy, rw, rh, n=13, seed=0):
    random.seed(seed)
    pts = []
    for i in range(n):
        ang = 2 * math.pi * i / n + random.uniform(-0.18, 0.18)
        long = (rw if i % 2 == 0 else rw * 0.55)
        r = long * random.uniform(0.82, 1.18)
        pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r * (rh / rw if rw else 1)))
    return pts


def dashes_on_ellipse(draw, cx, cy, bw, bh, border, seg=20, gap=0.45):
    for i in range(seg):
        a0 = 2 * math.pi * i / seg
        a1 = a0 + 2 * math.pi / seg * (1 - gap)
        steps = 6
        pts = []
        for k in range(steps + 1):
            a = a0 + (a1 - a0) * k / steps
            pts.append((cx + math.cos(a) * bw / 2, cy + math.sin(a) * bh / 2))
        draw.line(pts, fill="black", width=border, joint="curve")


def put_text(draw, cx, cy, text, font, max_w, color="#2B2B2B"):
    lines = wrap_text(draw, text, font, max_w)
    lh = int(font.size * 1.3)
    y0 = cy - (len(lines) - 1) * lh / 2
    for i, l in enumerate(lines):
        draw.text((cx, y0 + i * lh), l, font=font, fill=color, anchor="mm")


def tone_params(tone, border):
    """返回 (border, jitter) — shonen 粗+手绘微抖，shoujo 细+平滑。"""
    if tone == "shoujo":
        return int(border * 0.85), 0.0
    return int(border * 1.15), border * 0.06  # shonen/auto：极轻微长波，线基本均匀干净


def shape_ellipse(draw, cx, cy, bw, bh, border, tail, tone, seed=0):
    border, _ = tone_params(tone, border)
    if tail == "none":
        draw.ellipse([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2],
                     fill="white", outline="black", width=border)
        return
    _paint_bubble(draw._image, cx, cy, bw / 2, bh / 2, tail, border)


def shape_rounded(draw, cx, cy, bw, bh, border, tail, tone, radius=42):
    border, _ = tone_params(tone, border)
    if tail == "none":
        draw.rounded_rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2],
                               radius=radius, fill="white", outline="black", width=border)
        return
    _paint_bubble(draw._image, cx, cy, bw / 2, bh / 2, tail, border,
                  body="rounded", radius=radius)


def shape_circle(draw, cx, cy, r, border, tail, tone, seed=0):
    border, _ = tone_params(tone, border)
    if tail == "none":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="white", outline="black", width=border)
        return
    _paint_bubble(draw._image, cx, cy, r, r, tail, border)


def shape_petal(draw, cx, cy, rw, rh, border, tail, tone, seed=0):
    border, jitter = tone_params(tone, border)
    amp = 0.17 if tone == "shoujo" else 0.14
    body = petal_points(cx, cy, rw, rh, lobes=7, amp=amp, jitter=jitter, seed=seed)
    tail_pts = tail_polygon(cx, cy, rw * 2, rh * 2, tail, curve=0.10,
                            jitter=jitter * 0.4, seed=seed) if tail and tail != "none" else None
    _paint_polygon_bubble(draw, body, tail_pts, border)


def shape_trumpet(draw, cx, cy, top_w, bot_w, h, border, tail, tone):
    border, _ = tone_params(tone, border)
    body = [(cx - top_w / 2, cy - h / 2), (cx + top_w / 2, cy - h / 2),
            (cx + bot_w / 2, cy + h / 2), (cx - bot_w / 2, cy + h / 2)]
    tail_pts = tail_polygon(cx, cy, top_w, h, tail, curve=0.10) if tail and tail != "none" else None
    _paint_polygon_bubble(draw, body, tail_pts, border)


def shape_quad(draw, cx, cy, rw, rh, border, tail, tone, seed=0):
    border, jitter = tone_params(tone, border)
    random.seed(seed)
    # v2.9.9 修复：原顶点纵向只到 ±0.42~0.52 rh（实际高度仅文字块一半，长文案上下必出框）
    base = [(cx - rw * 0.92, cy - rh * 0.90), (cx + rw * 0.82, cy - rh * 0.94),
            (cx + rw * 0.96, cy + rh * 0.90), (cx - rw * 0.86, cy + rh * 0.92)]
    if jitter > 0:
        jx = jitter * 1.2
        base = [(x + random.uniform(-jx, jx), y + random.uniform(-jx, jx)) for x, y in base]
    tail_pts = tail_polygon(cx, cy, rw * 2, rh * 2, tail, curve=0.10,
                            jitter=jitter * 0.4, seed=seed) if tail and tail != "none" else None
    _paint_polygon_bubble(draw, base, tail_pts, border)


def shape_burst(draw, cx, cy, rw, rh, border, tone, seed=0):
    border, _ = tone_params(tone, border)
    draw.polygon(burst_points(cx, cy, rw, rh, n=13, seed=seed),
                 fill="white", outline="black", width=border)


def shape_thought(draw, cx, cy, rw, rh, border, tone, seed=0):
    border, jitter = tone_params(tone, border)
    draw.polygon(petal_points(cx, cy, rw, rh, lobes=9, amp=0.18, jitter=jitter, seed=seed),
                 fill="white", outline="black", width=max(2, border - 1))
    # v2.9.9：三个小圆不再死板垂直向下，沿斜向排列（上/下左右都有角度）
    _rnd = random.Random(int(seed) * 31 + 7)
    _drift = rw * _rnd.uniform(0.16, 0.38) * (1 if _rnd.random() < 0.5 else -1)
    for k, (dy, rr) in enumerate([(rh * 1.05, rw * 0.22), (rh * 1.35, rw * 0.14), (rh * 1.6, rw * 0.08)]):
        _kx = cx + _drift * (k + 1) * 0.55
        draw.ellipse([_kx - rr, cy + dy - rr, _kx + rr, cy + dy + rr],
                     fill="white", outline="black", width=max(2, border - 2))


def shape_wave(draw, cx, cy, rw, rh, border, tail, tone, seed=0):
    border, jitter = tone_params(tone, border)
    amp = 0.07 if tone != "shoujo" else 0.05
    body = wave_points(cx, cy, rw, rh, amp=amp, freq=20, jitter=jitter, seed=seed)
    tail_pts = tail_polygon(cx, cy, rw * 2, rh * 2, tail, curve=0.10,
                            jitter=jitter * 0.4, seed=seed) if tail and tail != "none" else None
    _paint_polygon_bubble(draw, body, tail_pts, border)


def shape_mini(draw, cx, cy, rw, rh, border, tail, tone, seed=0):
    border, _ = tone_params(tone, border)
    bw = max(2, border - 2)
    if tail == "none":
        draw.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill="white", outline="black", width=bw)
        return
    _paint_bubble(draw._image, cx, cy, rw, rh, tail, bw)


def shape_freehand(draw, cx, cy, rw, rh, border, tail, tone, seed=0):
    border, jitter = tone_params(tone, border)
    jitter = max(jitter, border * 1.6)
    body = petal_points(cx, cy, rw, rh, lobes=6, amp=0.10, jitter=jitter, seed=seed)
    tail_pts = tail_polygon(cx, cy, rw * 2, rh * 2, tail, curve=0.10,
                            jitter=jitter * 0.4, seed=seed) if tail and tail != "none" else None
    _paint_polygon_bubble(draw, body, tail_pts, border)


def shape_whisper(draw, cx, cy, bw, bh, border, tail, tone):
    border, _ = tone_params(tone, border)
    draw.polygon(tail_polygon(cx, cy, bw, bh, tail, curve=0.10), fill="white", outline="black")
    draw.ellipse([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], fill="white", outline=None)
    dashes_on_ellipse(draw, cx, cy, bw, bh, max(2, border - 2))


def shape_caption(draw, cx, cy, bw, bh, border, tone, radius=30):
    border, _ = tone_params(tone, border)
    draw.rounded_rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2],
                           radius=radius, fill="white", outline="black", width=border)


def shape_double(draw, cx, cy, bw, bh, border, tail, tone, seed=0):
    border, _ = tone_params(tone, border)
    # 双层：外粗 : 间隙 : 内细 ≈ 3:5:1.5；尾巴用连续尖凸贯穿双层，圆润无横切
    ow, iw = int(border * 1.3), max(2, int(border * 0.45))
    rx_o, ry_o = bw / 2 * 1.48, bh / 2 * 1.48
    if tail == "none":
        draw.ellipse([cx - rx_o, cy - ry_o, cx + rx_o, cy + ry_o], fill="white", outline="black", width=ow)
        draw.ellipse([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], fill=None, outline="black", width=iw)
        return
    _paint_bubble(draw._image, cx, cy, rx_o, ry_o, tail, ow, fill_interior=True)
    _paint_bubble(draw._image, cx, cy, bw / 2, bh / 2, tail, iw, fill_interior=False)


# v2.9.9：文字块相对形状的占比——圆/星/云/异形轮廓的内切区小于包围盒，
# 文字必须按比例缩小才能待在轮廓内（此前文字块 = 包围盒尺寸，长文案必出框）
TEXT_FIT = {
    'ellipse': 0.80, 'shoujo': 0.80, 'rounded': 0.92, 'caption': 0.92,
    'double': 0.86, 'whisper': 0.86, 'mini': 0.84, 'wave': 0.82,
    'freehand': 0.82, 'petal': 0.76, 'circle': 0.72, 'trumpet': 0.74,
    'quad': 0.74, 'burst': 0.56, 'thought': 0.58,
}


def draw_bubble(draw, style, cx, cy, text, font, border, tail, tone, seed=0,
                fit=True, wrap_w=None):
    """统一入口：先按形状画白底黑边，再写文字（多行自动换行不溢出）。

    v2.9.9：① 尾巴斜向化（skew_direction），避免过于端正；
            ② 文字按 TEXT_FIT 比例缩字号，缩进异形轮廓内；
            ③ 断行只算一次（此前 draw_bubble 与 put_text 各断一次，行数/高度错配导致压出框）。
    """
    tail = skew_direction(tail, seed)
    k = TEXT_FIT.get(style, 0.80) if fit else 1.0
    _wrap = int(wrap_w) if wrap_w else max(int(font.size * 2), int(font.size * 11))
    lines = wrap_text(draw, text, font, _wrap)
    max_line = max(draw.textlength(l, font=font) for l in lines) if lines else 10
    lh0 = int(font.size * 1.3)
    pad_x = int(font.size * 1.05)
    pad_y = int(font.size * 0.90)
    tw = max_line
    bw = tw + 2 * pad_x
    bh = len(lines) * lh0 + 2 * pad_y

    if style == "circle":
        r = max(bw, bh) / 2
        shape_circle(draw, cx, cy, r, border, tail, tone, seed)
    elif style == "rounded":
        shape_rounded(draw, cx, cy, bw, bh, border, tail, tone)
    elif style == "petal":
        shape_petal(draw, cx, cy, bw / 2, bh / 2, border, tail, tone, seed)
    elif style == "trumpet":
        shape_trumpet(draw, cx, cy, bw * 0.55, bw, bh, border, tail, tone)
    elif style == "quad":
        shape_quad(draw, cx, cy, bw / 2, bh / 2, border, tail, tone, seed)
    elif style == "burst":
        shape_burst(draw, cx, cy, bw / 2, bh / 2, border, tone, seed)
    elif style == "thought":
        shape_thought(draw, cx, cy, bw / 2, bh / 2, border, tone, seed)
    elif style == "wave":
        shape_wave(draw, cx, cy, bw / 2, bh / 2, border, tail, tone, seed)
    elif style == "mini":
        shape_mini(draw, cx, cy, bw / 2, bh / 2, border, tail, tone)
    elif style == "freehand":
        shape_freehand(draw, cx, cy, bw / 2, bh / 2, border, tail, tone, seed)
    elif style == "whisper":
        shape_whisper(draw, cx, cy, bw, bh, border, tail, tone)
    elif style == "caption":
        shape_caption(draw, cx, cy, bw, bh, border, tone)
    elif style == "double":
        shape_double(draw, cx, cy, bw, bh, border, tail, tone, seed)
    else:  # ellipse / shoujo
        if style == "shoujo":
            border, _ = tone_params("shoujo", border)
            _paint_bubble(draw._image, cx, cy, bw / 2, bh / 2, tail, border)
        else:
            shape_ellipse(draw, cx, cy, bw, bh, border, tail, tone, seed)

    # 文字：按 k 比例缩字号后居中排（复用同一套断行结果，绝不二次断行）
    tfs = max(int(font.size * 0.5), int(font.size * k))
    try:
        tfont = font.font_variant(size=tfs)
    except Exception:
        tfont = load_font(DEFAULT_TEXT_FONT, tfs)
    lh = int(tfs * 1.3)
    dy = bh * (0.05 if style == "trumpet" else (-0.12 if style == "thought" else 0.0))
    y0 = cy + dy - (len(lines) - 1) * lh / 2
    for i, l in enumerate(lines):
        draw_mixed_text(draw, cx, y0 + i * lh, l, tfont, _BUBBLE_TEXT)


def draw_sfx(draw, cx, cy, text, font, color="black", outline_color="white",
             style="burst", seed=0):
    if style == "plain":
        draw_mixed_text(draw, cx, cy, text, font, color,
                        stroke_width=max(2, int(font.size * 0.09)), stroke_fill=outline_color)
        return
    if style == "ring":
        # v2.9.10：装饰圈按词宽缩放，长词不再把文字顶出圈外
        _tw = draw.textlength(text, font=font)
        _base = max(font.size * 1.0, _tw / 2 + font.size * 0.30)
        for _k in (1.15, 1.45, 1.75):
            rr = _base * _k
            draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                         outline=color, width=max(1, int(font.size * 0.03)))
        draw_mixed_text(draw, cx, cy, text, font, color,
                        stroke_width=max(2, int(font.size * 0.09)), stroke_fill=outline_color)
        return
    if style == "lines":
        # v2.9.10：放射线按词宽缩放
        _tw = draw.textlength(text, font=font)
        _base = max(font.size * 1.0, _tw / 2 + font.size * 0.22)
        for ang in range(0, 360, 30):
            rad = math.radians(ang)
            draw.line([cx + math.cos(rad) * _base * 1.10, cy + math.sin(rad) * _base * 1.10,
                       cx + math.cos(rad) * _base * 1.48, cy + math.sin(rad) * _base * 1.48],
                      fill=color, width=max(1, int(font.size * 0.04)))
        draw_mixed_text(draw, cx, cy, text, font, color,
                        stroke_width=max(2, int(font.size * 0.09)), stroke_fill=outline_color)
        return
    # burst：不规则爆炸形框（单层粗黑描边 + 白底）
    # v2.9.10 修复出框：星形凹口半径只有尖半径的 0.55（≈0.45×），
    # 原 rw=tw/2+0.55fs 只够单字；改为按内切比例给足，2~6 字均不出框
    tw = draw.textlength(text, font=font)
    rw = tw * 1.18 + font.size * 0.42
    rh = max(font.size * 1.62, font.size * 0.62)
    border = max(3, int(font.size * 0.13))
    pts_o = burst_points(cx, cy, rw, rh, n=13, seed=seed)
    draw.polygon(pts_o, fill="white", outline="black", width=border)
    draw_mixed_text(draw, cx, cy, text, font, color)


def main():
    ap = argparse.ArgumentParser(description="把漫画风配文叠加到照片转漫画的底图")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--bubble", default=None)
    ap.add_argument("--bubble-style", default="ellipse",
                    choices=["ellipse", "rounded", "circle", "petal", "trumpet", "quad",
                             "burst", "thought", "wave", "mini", "freehand", "whisper",
                             "caption", "double", "shoujo"])
    ap.add_argument("--bubble-tone", default="auto", choices=["auto", "shonen", "shoujo"])
    ap.add_argument("--bubble-pos", default="tr", choices=["tl", "tr", "bl", "br"])
    ap.add_argument("--bubble-xy", default=None, help="手动坐标 'x,y' 归一化（规避挡脸）")
    ap.add_argument("--bubble-tail", default=None)
    ap.add_argument("--bubble-fill", default="white")
    ap.add_argument("--bubble-outline", default="black")
    ap.add_argument("--bubble-text", default="#2B2B2B")
    ap.add_argument("--sfx", default=None)
    ap.add_argument("--sfx-pos", default="right")
    ap.add_argument("--sfx-xy", default=None)
    ap.add_argument("--sfx-style", default="burst", choices=["burst", "plain", "ring", "lines"])
    ap.add_argument("--sfx-color", default="black")
    ap.add_argument("--sfx-outline", default="white")
    ap.add_argument("--sfx-seed", type=int, default=0)
    ap.add_argument("--label", default=None)
    ap.add_argument("--title-color", default="#2B2B2B")
    ap.add_argument("--title-font", default=DEFAULT_TITLE_FONT)
    ap.add_argument("--text-font", default=DEFAULT_TEXT_FONT)
    ap.add_argument("--title-font-index", type=int, default=0)
    ap.add_argument("--no-bubble", action="store_true")
    ap.add_argument("--no-label", action="store_true")
    ap.add_argument("--decor", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    global _BUBBLE_TEXT
    _BUBBLE_TEXT = args.bubble_text
    tone = "shonen" if args.bubble_tone == "auto" else args.bubble_tone

    if not os.path.exists(args.input):
        sys.exit("[render_text] 输入图不存在: %s" % args.input)

    img = Image.open(args.input).convert("RGBA")
    W, H = img.size
    draw = ImageDraw.Draw(img)

    title_size = max(28, int(W * 0.10))
    bubble_size = max(20, int(W * 0.058))
    sfx_size = max(18, int(W * 0.050))
    label_size = max(14, int(W * 0.034))

    title_font = load_font(args.title_font, title_size, args.title_font_index)
    bubble_font = load_font(args.text_font, bubble_size)
    sfx_font = load_font(args.title_font, sfx_size)
    label_font = load_font(args.text_font, label_size)

    if args.decor:
        random.seed(args.seed)
        a = list(ImageColor.getrgb("#F48FB1")) + [120]
        for _ in range(6):
            r = random.randint(int(W * 0.006), int(W * 0.014))
            x = random.choice([random.randint(int(W * 0.05), int(W * 0.25)),
                               random.randint(int(W * 0.75), int(W * 0.95))])
            y = random.choice([random.randint(int(H * 0.05), int(H * 0.25)),
                               random.randint(int(H * 0.75), int(H * 0.95))])
            draw.ellipse([x - r, y - r, x + r, y + r], fill=tuple(a))

    if args.bubble and not args.no_bubble:
        pos_map = {
            "tl": (W * 0.30, H * 0.18),
            "tr": (W * 0.70, H * 0.18),
            "bl": (W * 0.30, H * 0.78),
            "br": (W * 0.70, H * 0.78),
        }
        if args.bubble_xy:
            fx, fy = [float(v) for v in args.bubble_xy.split(",")]
            cx, cy = fx * W, fy * H
        else:
            cx, cy = pos_map[args.bubble_pos]
        # —— 防溢出夹紧：确保气泡整体留在画布内（经验教训：长句单行会超出画布被裁导致断字） ——
        _est_lines = wrap_text(draw, args.bubble, bubble_font, int(bubble_font.size * 11))
        _est_max = max(draw.textlength(l, font=bubble_font) for l in _est_lines) if _est_lines else 10
        _bw = _est_max + 2 * int(bubble_font.size * 1.05)
        _bh = len(_est_lines) * int(bubble_font.size * 1.3) + 2 * int(bubble_font.size * 0.90)
        _mgn = int(W * 0.02)
        cx = max(_mgn + _bw / 2, min(cx, W - _mgn - _bw / 2))
        cy = max(_mgn + _bh / 2, min(cy, H - _mgn - _bh / 2))
        tail = args.bubble_tail or ("bl" if cx > W / 2 else "br")
        border = max(3, int(W * 0.006))
        draw_bubble(draw, args.bubble_style, cx, cy, args.bubble,
                    bubble_font, border, tail, tone, seed=args.seed)

    if args.sfx:
        if args.sfx_xy:
            fx, fy = [float(v) for v in args.sfx_xy.split(",")]
            cx, cy = fx * W, fy * H
        else:
            smap = {"left": (W * 0.20, H * 0.55), "right": (W * 0.80, H * 0.55),
                    "top": (W * 0.5, H * 0.20), "bottom": (W * 0.5, H * 0.82)}
            cx, cy = smap.get(args.sfx_pos, (W * 0.8, H * 0.55))
        border = max(3, int(W * 0.006))
        draw_sfx(draw, cx, cy, args.sfx, sfx_font, args.sfx_color,
                 args.sfx_outline, args.sfx_style, seed=args.sfx_seed)

    if args.title and not args.no_label:
        draw.text((W * 0.5, H * 0.06), args.title, font=title_font,
                  fill=args.title_color, anchor="mm")
    if args.label and not args.no_label:
        draw.text((W * 0.5, H * 0.95), args.label, font=label_font,
                  fill="#666666", anchor="mm")

    img.convert("RGB").save(args.output)
    print("[render_text] 已保存: " + args.output)


if __name__ == "__main__":
    main()