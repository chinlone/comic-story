#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comic_story.py — 漫画故事定稿渲染脚本（配合图生图保真底图使用）

排版范式（对齐用户提供的多张参考漫画图，且每次可随机/按场景变化，禁止千篇一律）：
  double  双人/场景：两个横排椭圆对话框（角色台词 + 旁白环境音）+ 白色弧线速度线
  single  单人特写：支持多种布局，每次随场景/随机变化——
            · 主框方位：竖排椭圆在右(v_right)/在左(v_left)，或横排圆角矩形在上(h_top)/在下(h_bottom)
            · 唰 burst 方位：下/上/左/右/对角，随机或指定，绝不叠主框
            · 竖排椭圆尾巴方向随主框方位自适应（脸在右则尾朝左，脸在左则尾朝右）
默认字体：对话框=ZCOOLKuaiLe 圆润手写（rt.DEFAULT_TEXT_FONT）；唰/burst=系统粗印刷体（rt.DEFAULT_TITLE_FONT）

布局多样性铁律：single 默认 layout='auto'（随机选一种），sfx_pos='auto'（随机选一个不重叠方位）。
可显式指定 --layout / --sfx_pos 锁定，但不得对所有图都用同一固定组合。
"""

import sys, os, argparse, math, random, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_text as rt
import symbols as symlib   # v2.10：情绪符号层（纯程序绘制）
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops

FONT = rt.DEFAULT_TEXT_FONT        # 圆润手写体（对话框）
TITLE_FONT = FONT  # v2.9.10：拟声词也改用技能内打包字体（OFL 免费商用），
#   不再依赖系统 NotoSansSC 路径，避免换环境字体缺失直接崩

# ===== 对话框库（定稿·从库里来，禁止乱画）=====
# 八方向尾巴：4 正 + 4 斜（已视觉终检：均一体无封边连续）
TAIL_DIRS_8 = ['left', 'right', 'top', 'bottom', 'tl', 'tr', 'br', 'bl']
# 其余带尾形状池（竖排椭圆为定稿特例，单独走 draw_v_bubble，不在此池）
SHAPE_POOL = ['rounded', 'circle', 'petal', 'quad', 'wave', 'freehand', 'mini', 'shoujo']
# 场景 → 形状偏好池（对齐 SKILL.md，池内随机不锁死）
SCENE_SHAPES = {
    'people': ['rounded', 'circle', 'petal', 'mini'],
    'nature': ['rounded', 'circle', 'wave', 'petal'],
    'food':   ['rounded', 'circle', 'petal', 'mini'],
    'pet':    ['rounded', 'circle', 'petal', 'mini'],
    'sport':  ['rounded', 'circle', 'quad', 'burst'],
    'city':   ['rounded', 'circle', 'quad'],
    'unknown':['rounded', 'circle', 'petal'],
}


def wrap_chars(text, font, max_w):
    lines, cur = [], ''
    for ch in text:
        if font.getlength(cur + ch) <= max_w:
            cur += ch
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_h_bubble(draw, W, H, box, text, font):
    """横排圆角矩形对话框：自适应缩小字号，保证换行后文字完全落在框内（绝不截断/溢出）"""
    x, y, w, h = box
    border = max(4, int(W * 0.006))
    pad_x = int(W * 0.035)
    pad_y = int(H * 0.018)
    # 从传入字号起逐步缩小，直到文字（行宽+行高）都落在框内
    # v2.9.9：字号下限 0.018W → 0.012W；仍放不下则向上加高框（底边固定、不越界），
    #         根治「双人模式长文案文字压出框」（实测 70 字出框 15.7%、120 字 45.3%）
    fs_min = max(12, int(W * 0.012))
    fs = int(font.size)
    fit = None
    while fs >= fs_min:
        f = rt.load_font(FONT, fs)
        lines = wrap_chars(text, f, w - 2 * pad_x)
        lh = f.getbbox('测')[3] + int(H * 0.006)
        need_h = len(lines) * lh + 2 * pad_y
        need_w = max((f.getlength(l) for l in lines), default=0)
        if need_h <= h and need_w <= w - 2 * pad_x:
            fit = (f, lines, lh)
            break
        fs -= 2
    if fit is None:
        f = rt.load_font(FONT, fs_min)
        lines = wrap_chars(text, f, w - 2 * pad_x)
        lh = f.getbbox('测')[3] + int(H * 0.006)
        need_h = len(lines) * lh + 2 * pad_y
        h = min(int(H * 0.94), max(h, need_h))
        y = max(int(H * 0.02), H - h - int(H * 0.02))
        fit = (f, lines, lh)
    font, lines, lh = fit
    draw.rounded_rectangle([x, y, x + w, y + h], radius=min(w, h) * 0.22,
                           fill='white', outline='black', width=border)
    total = (len(lines) - 1) * lh
    ty = y + h / 2 - total / 2
    for line in lines:
        rt.draw_mixed_text(draw, x + w / 2, ty, line, font, '#2B2B2B')   # v2.9.10 缺字兜底
        ty += lh
    return (x, y, x + w, y + h)


def _merged_bent_outline(cx, cy, rx, ry, direction, border, bend=0.0, seed=0):
    """椭圆+尾巴一体连续轮廓（无封边），尾巴带侧向弧度（bend>0 下弯）。"""
    theta = {'right': 0.0, 'bottom': math.pi / 2, 'left': math.pi, 'top': -math.pi / 2}[direction]
    horiz = direction in ('left', 'right')
    tail_len = (rx if horiz else ry) * 0.50
    Rr = (rx * ry) / math.sqrt((ry * math.cos(theta)) ** 2 + (rx * math.sin(theta)) ** 2)
    w = 2 * math.asin(min(border * 2.6, Rr * 0.18) / (2 * Rr)); w = max(w, 0.12)
    M = 360
    c_dir, s_dir = math.cos(theta), math.sin(theta)
    nx, ny = -s_dir, c_dir
    pts = []
    for i in range(M + 1):
        th = 2 * math.pi * i / M
        x = cx + rx * math.cos(th); y = cy + ry * math.sin(th)
        d = rt._angle_diff(th, theta)
        if abs(d) < w:
            u = abs(d) / w
            extra = tail_len * (1 - u) ** 3.0
            ex, ey = rx * math.cos(th), ry * math.sin(th); en = math.hypot(ex, ey) or 1
            x += ex / en * extra; y += ey / en * extra
            x += nx * bend * u; y += ny * bend * u
        pts.append((x, y))
    return pts


def draw_v_bubble(draw, W, H, cx, cy, text, tail_dir='left', h_threshold=8):
    """照片故事式对话框（白底黑粗描边+尾巴，贴合原厂样图）：
    - 短文本(≤h_threshold字)走【横排椭圆】（原厂横排为主，不溢出）
    - 长文本走【竖排胶囊】（恒定宽度，防竖排文字柱横向溢出出框）
    tail_dir: 'left' 尾巴朝左(脸在右); 'right' 尾巴朝右(脸在左)"""
    chars = list(text)
    n = len(chars)
    border = max(4, int(W * 0.006))
    tail_d = 'left' if tail_dir == 'left' else 'right'
    if n <= h_threshold:
        # —— 横排椭圆（原厂主流）——
        font = rt.load_font(FONT, int(min(W, H) * 0.052))
        tw = draw.textlength(text, font=font)
        rx = tw / 2 + int(W * 0.045)
        ry = int(W * 0.052) / 2 + int(W * 0.030)
        # v2.9.8 修复：先把中心夹进画布内，避免越界后兜底重画造成「双对话框」
        if 2 * rx <= W - 20:
            cx = min(max(cx, rx + 10), W - rx - 10)
        else:
            cx = W // 2
        if 2 * ry <= H - 20:
            cy = min(max(cy, ry + 10), H - ry - 10)
        else:
            cy = H // 2
        tail_d = rt.skew_direction(tail_d, seed=sum(map(ord, text)) % 97 + 11)  # v2.9.9 尾巴斜向
        rt._paint_bubble(draw._image, cx, cy, rx, ry, tail_d, border, body="ellipse")
        rt.draw_mixed_text(draw, cx, cy, text, font, '#2B2B2B')   # v2.9.10 缺字兜底
        return (cx - rx, cy - ry, cx + rx, cy + ry)
    else:
        if W > H:
            # —— 横图长文本：横排大字 + 自动换行（横向空间足，可读性最佳，不压成竖排小字）——
            fs = int(min(W, H) * 0.048)
            font = rt.load_font(FONT, fs)
            # v2.12.3：横图长文本框宽从 0.66W 收到 0.34W（原来一个框横跨三分之二画面，
            # 严重遮挡照片、违反「单框面积≤4%」守则），高度自适应、贴底居中
            w = int(W * 0.34); h = int(H * 0.16)
            x = (W - w) // 2
            y = int(H - h - H * 0.06)  # 贴底，给上方语气词留空间
            main_box = draw_h_bubble(draw, W, H, (x, y, w, h), text, font)
            return main_box
        # —— 竖图长文本：竖排多列（像横排换行一样，列满则换列，字号保持大）——
        fs = int(W * 0.035)            # 舒适大字，不压到很小
        font = rt.load_font(FONT, fs)
        ls = int(fs * 1.18)            # 列内字纵向间距
        col_gap = int(fs * 0.55)       # 列间距
        col_w = int(fs * 1.05)         # 单列宽
        pad_x = int(W * 0.025); pad_y = int(H * 0.02)
        # 每列最多字数（由可用高度决定），超了换下一列（漫画纵书从右到左）
        avail_h = H - 2 * pad_y
        per_col = max(1, int(avail_h / ls))
        cols = math.ceil(n / per_col)
        # 实际各列字数（末列可能不满），框高按最大列字数，避免统一满列高造成的上下留白
        _col_lens = [len(chars[c * per_col:(c + 1) * per_col]) for c in range(cols)]
        col_h = max(_col_lens) * ls + 2 * pad_y
        bh = col_h
        bw = cols * col_w + (cols - 1) * col_gap + 2 * pad_x
        if cx + bw // 2 > W - 10:
            cx = W - 10 - bw // 2
        if cx - bw // 2 < 10:
            cx = bw // 2 + 10
        # v2.9.8 修复：竖排框垂直方向同样夹进画布，避免双框
        if 2 * bh <= H - 20:
            cy = min(max(cy, bh // 2 + 10), H - bh // 2 - 10)
        else:
            cy = H // 2
        radius = int(min(bw, bh) * 0.25)
        tail_d = rt.skew_direction(tail_d, seed=sum(map(ord, text)) % 89 + 7)  # v2.9.9 尾巴斜向
        rt._paint_bubble(draw._image, cx, cy, bw // 2, bh // 2, tail_d, border,
                         body="rounded", radius=radius)
        # 竖排多列绘制（第一列在最右，向左排）
        x_right = cx + (bw // 2 - pad_x) - col_w // 2
        for c in range(cols):
            col_chars = chars[c * per_col:(c + 1) * per_col]
            col_cx = x_right - c * (col_w + col_gap)
            top = cy - (len(col_chars) - 1) * ls // 2
            for i, ch in enumerate(col_chars):
                _f = rt._fallback_font(font.size) if ch in rt._missing_chars() else font
                draw.text((col_cx, top + i * ls), ch, font=_f, fill='#2B2B2B', anchor='mm')
        return (cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2)


def draw_from_library(draw, W, H, cx, cy, text, scene, seed, forbid=None):
    """从对话框库随机选形状 + 八方向随机尾巴（禁止乱画）。
    竖排椭圆定稿走 draw_v_bubble，不在此池；其余带尾形状全放开。
    forbid: 按布局排除会压脸的方向（如横排在顶部则尾巴不朝下）。"""
    random.seed(seed if seed else None)
    pool = SCENE_SHAPES.get(scene, SCENE_SHAPES['unknown'])
    shape = random.choice(pool)
    dirs = [d for d in TAIL_DIRS_8 if d not in (forbid or [])]
    tail = random.choice(dirs)
    font = rt.load_font(FONT, int(W * 0.045))
    border = max(4, int(W * 0.006))
    rt.draw_bubble(draw, shape, cx, cy, text, font, border, tail, 'shonen', seed=seed + 1)
    # 估算真实气泡外接包围盒（与 rt.draw_bubble 同口径），返回给 SFX 作安全位基准
    # —— 这是根治“语气词压对话框”的关键：SFX 必须基于真实气泡外缘计算，而非固定大框
    half = _est_bubble_half(draw, text, W)
    pad = border + int(W * 0.012)
    return (int(cx - half - pad), int(cy - half - pad),
            int(cx + half + pad), int(cy + half + pad))


def _est_bubble_half(draw, text, W):
    """估算对话框（与 rt.draw_bubble 同口径）外接半边长，供布局避让/夹取使用"""
    font = rt.load_font(FONT, int(W * 0.045))
    lines = rt.wrap_text(draw, text, font, int(font.size * 11))
    if lines:
        tw = max(draw.textlength(l, font=font) for l in lines)
        bh_txt = len(lines) * int(font.size * 1.3) + 2 * int(font.size * 0.90)
    else:
        tw, bh_txt = 10, int(font.size * 1.3)
    bw = tw + 2 * int(font.size * 1.05)
    return max(bw, bh_txt) / 2.0   # 圆形 r=max(bw,bh)/2；其余形状保守取外接半边长


def _clip_rect(p0, p1, rect):
    """Liang-Barsky：返回线段 p0->p1 与矩形 rect 的「内部」参数区间 [t0,t1]（均在[0,1]），
    无交返回 None。用于边缘线在碰到主体包围盒前截断。"""
    x0, y0 = p0; x1, y1 = p1
    xmin, ymin, xmax, ymax = rect
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0),
                 (-dy, y0 - ymin), (dy, ymax - y0)):
        if p == 0:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return None
                if r < t1:
                    t1 = r
    return (t0, t1)


def draw_speedlines(draw, W, H, cx, cy, style='arc', keepout=None, base_img=None):
    """动感线（speed lines / 集中线）。
    style='arc'  : 旧版——9 条白色半透明弧线居中环绕主体（横跨脸/头顶，人物照慎用）。
    style='edge' : 四周边缘集中线——从画布四边指向中心；以 keepout 主体包围盒做矩形裁剪，
                   线条在碰到人物前即截断，中心与人物区干净、绝不遮挡。用户建议方案。
    keepout     : (x0,y0,x1,y1) 主体包围盒；None 则用默认居中框（0.35-0.65W, 0.25-0.55H）。
    """
    m = min(W, H)
    if style == 'edge':
        import random as _r
        _r.seed(11)
        diag = math.hypot(W, H)
        r_outer = diag * 0.62          # 起点在画布外/边缘之外
        if keepout is None:
            keepout = (int(0.35 * W), int(0.25 * H), int(0.65 * W), int(0.55 * H))
        M = int(m * 0.05)              # 主体框外扩留白，避免线条贴脸
        kx0, ky0, kx1, ky1 = (keepout[0] - M, keepout[1] - M,
                              keepout[2] + M, keepout[3] + M)
        n = 72
        for i in range(n):
            ang = 2 * math.pi * i / n + _r.uniform(-0.015, 0.015)
            dx, dy = math.cos(ang), math.sin(ang)
            x0, y0 = cx + dx * r_outer, cy + dy * r_outer   # 边缘外起点
            x1, y1 = cx, cy                                 # 指向中心
            clip = _clip_rect((x0, y0), (x1, y1), (kx0, ky0, kx1, ky1))
            segs = []
            if clip is None:
                segs = [((x0, y0), (x1, y1))]
            else:
                t0, t1 = clip
                # 线段参数化 P(t)=P0 + t*(C-P0)，C-P0=(-dx*r_outer, -dy*r_outer)
                if t0 > 1e-3:   # 画框「外侧」段（边缘 -> 入框点）
                    segs.append(((x0, y0), (x0 - dx * r_outer * t0, y0 - dy * r_outer * t0)))
                if t1 < 1 - 1e-3:  # 画框「内侧」段（出框点 -> 中心）
                    segs.append(((x0 - dx * r_outer * t1, y0 - dy * r_outer * t1), (x1, y1)))
            w = _r.choice([max(2, int(W * 0.0025)), max(3, int(W * 0.004))])
            a = _r.randint(85, 150)
            for (pa, pb) in segs:
                draw.line([pa[0], pa[1], pb[0], pb[1]], fill=(255, 255, 255, a), width=w)
        return
    if style == 'burst':
        import random as _r
        _r.seed(11)
        if keepout is None:
            keepout = (int(0.35 * W), int(0.25 * H), int(0.65 * W), int(0.55 * H))
        ccx = (keepout[0] + keepout[2]) / 2.0
        ccy = (keepout[1] + keepout[3]) / 2.0
        kw = keepout[2] - keepout[0]; kh = keepout[3] - keepout[1]
        r0 = 0.5 * math.hypot(kw, kh) * 1.5 + int(m * 0.04)  # 从人物框外出发，不挡人
        tone = 255
        if base_img is not None:
            try:
                sm = base_img.resize((80, int(80 * H / W))).convert('L')
                px = list(sm.getdata()); tone = sum(px) / len(px)
            except Exception:
                tone = 255
        ink = 0 if tone >= 135 else 255     # 主色：亮背景黑、暗背景白
        alt = 255 - ink                     # 反色高光：同图里黑中有白、白中有黑
        far = math.hypot(W, H)
        # 聚簇发射：K 个随机主方向，每束散布几根 -> 有疏有密、灵动（非满屏均匀）
        # 整体均匀覆盖：把 360° 均分成 total 个扇区，每扇区 1 根、角度小幅抖动
        # -> 各方向都有线、不聚簇；灵动靠单线自身的断续/粗细/速度标记/长度随机
        total = _r.randint(48, 58)
        beams = []
        for i in range(total):
            sector = 2 * math.pi * i / total
            beams.append(sector + _r.uniform(-0.6 * math.pi / total, 0.6 * math.pi / total))
        for ang in beams:
            dx, dy = math.cos(ang), math.sin(ang)
            L = _r.uniform(r0 * 0.7, far * 1.05)         # 长短错落
            rr = r0 * _r.uniform(0.85, 1.2)              # 根不齐
            thick = _r.random() < 0.22                   # 少数粗主线，多数细线 -> 节奏
            w_in = (max(4, int(W * 0.006)) if thick
                    else _r.choice([max(2, int(W * 0.003)), max(1, int(W * 0.002))]))
            w_out = max(1, int(w_in * 0.35))             # 近端(人物侧)粗、远端(画外)细
            col = (alt, alt, alt, 255) if _r.random() < 0.28 else \
                  (ink, ink, ink, _r.choice([255, _r.randint(120, 170)]))
            # 断续：拆成数段，随机跳过 -> 手绘断裂感
            nseg = _r.randint(3, 5)
            for s in range(nseg):
                if _r.random() > 0.78:
                    continue
                t0s, t1s = s / nseg, (s + 1) / nseg
                p0x = ccx + dx * (rr + L * t0s) + _r.uniform(-2, 2)
                p0y = ccy + dy * (rr + L * t0s) + _r.uniform(-2, 2)
                p1x = ccx + dx * (rr + L * t1s) + _r.uniform(-2, 2)
                p1y = ccy + dy * (rr + L * t1s) + _r.uniform(-2, 2)
                mx = (p0x + p1x) / 2 + _r.uniform(-4, 4)
                my = (p0y + p1y) / 2 + _r.uniform(-4, 4)
                w = max(1, int(w_in + (w_out - w_in) * ((s + 0.5) / nseg)))
                draw.line([p0x, p0y, mx, my, p1x, p1y], fill=col, width=w)
            # 速度标记：部分线靠外处加短垂直交叉线（学参考图“速度标记”）
            if _r.random() < 0.3:
                tm = _r.uniform(0.55, 0.85)
                cxm = ccx + dx * (rr + L * tm); cym = ccy + dy * (rr + L * tm)
                pxv, pyv = -dy, dx
                hl = _r.uniform(int(W * 0.006), int(W * 0.014))
                draw.line([cxm - pxv * hl, cym - pyv * hl,
                           cxm + pxv * hl, cym + pyv * hl],
                          fill=col, width=max(1, int(w_out * 0.8)))
        return
    # 旧 arc 逻辑（居中弧线，人物照易挡脸）
    random.seed(7)
    for _ in range(9):
        r = random.uniform(0.30, 0.72) * m
        a0 = random.uniform(0, 2 * math.pi)
        a1 = a0 + random.uniform(0.5, 0.85)
        bbox = [cx - r, cy - r, cx + r, cy + r]
        draw.arc(bbox, math.degrees(a0), math.degrees(a1),
                 fill=(255, 255, 255, 120), width=max(2, int(W * 0.003)))


def main():
    main_box = None  # 函数级初始化，覆盖所有布局分支（含 double），避免 UnboundLocalError
    sfx_box = None  # 同上，sfx 框初始化（double 等不画 sfx 的分支也能安全引用）
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--mode', choices=['single', 'double'], default='single')
    ap.add_argument('--t1', default='')
    ap.add_argument('--t2', default='')
    ap.add_argument('--sfx', default='auto',
                    help="语气词：具体词 / 'auto'(按场景随机选，可能不配) / 'none'(无)")
    ap.add_argument('--scene', default='unknown',
                    choices=['unknown', 'people', 'nature', 'city', 'food', 'pet', 'sport'])
    ap.add_argument('--speedlines', dest='speedlines', action='store_const', const=True, default=None,
                    help="强制开启放射速度线（覆盖自动判定）")
    ap.add_argument('--no_speedlines', dest='speedlines', action='store_const', const=False, default=None,
                    help="强制关闭放射速度线（覆盖自动判定）")
    ap.add_argument('--auto_speedlines', action='store_true', default=True,
                    help="自动判定：禅意/端庄/静态/合照/演讲等场景自动关闭速度线（默认开；v2.8.1）")
    ap.add_argument('--speed_style', choices=['burst', 'edge'], default='burst',
                    help="speedlines 样式：burst=围绕人物向外放射(默认,不挡脸); edge=四周边缘集中线; arc=居中弧线(旧,易挡脸)")
    ap.add_argument('--ambient_style', choices=['none', 'swirl'], default='none',
                    help="氛围画法：none=不画(默认，动效由绘图模型画进底图)；swirl=程序兜底贴剪影环绕风线(仅模型画不出时用)")
    ap.add_argument('--swirl_n', type=int, default=5, help="swirl 圈数（默认5）")
    ap.add_argument('--wind_style', choices=['none', 'gust', 'spiral'], default='none',
                    help="风效：none=无(默认); gust=吹过风(3条平行S弧+辅弧+飘叶,配拟声词簌簌); spiral=旋绕风(扇形放射+头部同心弧+脚底螺旋+落叶)")
    ap.add_argument('--no_star', action='store_true', default=False,
                    help="swirl 模式不叠星芒光尘")
    # single 用：脸范围
    ap.add_argument('--fx0', type=int, default=0)  # 脸左缘 x（输出图像素，旧）
    ap.add_argument('--fx1', type=int, default=0)  # 脸右缘 x（输出图像素，旧）
    ap.add_argument('--fy0', type=int, default=0)
    ap.add_argument('--fy1', type=int, default=0)
    # 脸中心百分比（推荐）：fxc/fyc 为 0-100 的百分数，按真实底图尺寸换算，
    # 避免不同长宽比底图下固定像素错位导致 speedlines 穿脸。
    ap.add_argument('--fxc', type=int, default=0)  # 脸中心 x %
    ap.add_argument('--fyc', type=int, default=0)  # 脸中心 y %
    # 布局与唰位（auto=随机，避免每张图都一样）
    ap.add_argument('--layout', default='auto',
                    choices=['auto', 'v_right', 'v_left', 'h_top', 'h_bottom'])
    ap.add_argument('--sfx_pos', default='auto',
                    choices=['auto', 'none', 'down', 'up', 'left', 'right', 'diag'])
    ap.add_argument('--emotion', default='auto',
                    help="情绪符号：auto(按文案自动，默认阳光派) / none / 逗号分隔具体符号 "
                         "(sweat,tears,anger,exclaim,ask,heart,sparkle,blush,dark,dots)")
    ap.add_argument('--dark', action='store_true', default=False,
                    help="允许黑化派符号(dark排线/dots网点)——仅在用户明确要求黑化时打开")
    ap.add_argument('--seed', type=int, default=0)  # 0=随机种子
    a = ap.parse_args()
    a._boxes = []      # v2.10：收集所有文字框，供情绪符号避让
    a._shapes = []     # v2.11：记录本次实际用到的对话框形状（自检多样性）

    img = Image.open(a.input).convert('RGBA')
    W, H = img.size
    draw = ImageDraw.Draw(img)
    # 若提供脸中心百分比，按真实底图尺寸换算成脸框（覆盖旧像素参数）
    if a.fxc and a.fyc:
        cx_f, cy_f = a.fxc * W / 100.0, a.fyc * H / 100.0
        a.fx0 = int(cx_f - 0.11 * W)
        a.fx1 = int(cx_f + 0.11 * W)
        a.fy0 = int(cy_f - 0.20 * H)
        a.fy1 = int(cy_f + 0.20 * H)
    # 动效引擎（v2.8.5 照片感知）：按照片感知 + scene + 情绪词决策动效语言，再渲染高级氛围
    if a.speedlines is None:
        _amb = decide_ambient(img, getattr(a, 'scene', 'auto'), a.t1, a.t2, a.seed, a.mode)
        a._ambient_lang = _amb['lang']
        a.speedlines = (_amb['lang'] == 'speedlines')
        _fcx = (a.fx0 + a.fx1) / 2.0 if (a.fx0 and a.fx1) else W / 2.0
        _fcy = (a.fy0 + a.fy1) / 2.0 if (a.fy0 and a.fy1) else H * 0.42
        _keep = (a.fx0, a.fy0, a.fx1, a.fy1) if (a.fx0 and a.fx1 and a.fy0 and a.fy1) else None
        _amb['center'] = (_fcx, _fcy); _amb['keepout'] = _keep
        a._ambient_params = _amb
    else:
        a._ambient_lang = 'speedlines' if a.speedlines else 'zen'
        a._ambient_params = {'lang': a._ambient_lang, 'center': (W / 2.0, H * 0.42), 'keepout': None, 'warmth': 0.0}
    # 氛围动效（最底层）：按决策语言渲染融入照片的光影氛围
    # 静态场景环绕风（v2.8.7·默认 swirl）：贴剪影立体环绕风线；none 时不画（活动场景配 burst）
    if getattr(a, 'ambient_style', 'swirl') == 'swirl':
        a._ambient_drawn = draw_swirl_wind(draw, W, H, base_img=img, seed=a.seed,
                                           n_arcs=getattr(a, 'swirl_n', 5),
                                           star=not getattr(a, 'no_star', False))
    else:
        a._ambient_drawn = False
    # 风效（v2.8.8）：gust 吹过风 / spiral 旋绕风，画在氛围层之上、气泡之下
    if getattr(a, 'wind_style', 'none') == 'gust':
        draw_wind_gust(draw, W, H, base_img=img, seed=a.seed)
    elif getattr(a, 'wind_style', 'none') == 'spiral':
        draw_wind_spiral(draw, W, H, base_img=img, seed=a.seed)
    # 动感线（speedlines）先在底层绘制，气泡/语气词随后覆盖其上，避免压住对话框。
    if a.speedlines:
        ko = (a.fx0, a.fy0, a.fx1, a.fy1) if (a.fx0 and a.fx1 and a.fy0 and a.fy1) else None
        draw_speedlines(draw, W, H, int(0.5 * W), int(0.42 * H), a.speed_style, keepout=ko, base_img=img)

    # 语气词决定：auto 按场景随机选词（含概率不配），具体词直接用，none 无
    SFX_LIB = {   # v2.9.10：每场景扩充到 7~9 个，按"这个场景真会听到什么"选词
        'people':  ['唰', '咔嚓', '哒哒', '嗡', '咕噜', '呵呵', '叮', '噗嗤', '咔哒'],
        'nature':  ['哗啦', '沙沙', '簌簌', '呼呼', '窸窣', '啾', '淅沥', '潺潺', '呜咽'],
        'city':    ['嘀', '嗡', '哒哒', '轰', '咣当', '滴滴', '呼驰'],
        'food':    ['咕噜', '咔嚓', '哒哒', '呲啦', '咕嘟', '咔滋', '滋啦', '呼噜'],
        'pet':     ['汪', '喵', '啾', '哒哒', '喵呜', '汪汪', '呜噜', '哒哒哒'],
        'sport':   ['嘭', '呼', '咚', '砰', '咻', '呼哧', '噔噔', '啪'],
        'unknown': ['唰', '沙沙', '哗啦', '哒哒', '叮', '咔嚓'],
    }
    NONE_PROB = 0.35
    if a.sfx == 'none':
        word = None
    elif a.sfx == 'auto':
        word = None if random.random() < NONE_PROB else \
            random.choice(SFX_LIB.get(a.scene, SFX_LIB['unknown']))
    else:
        word = a.sfx

    if a.mode == 'double':
        f1 = rt.load_font(FONT, int(min(W, H) * 0.052))
        f2 = rt.load_font(FONT, int(min(W, H) * 0.046))
        # 群合影/双人：两框放【底部边角】（头顶在上方、底部是前景/身位，绝不会压脸）。
        # 原顶部两角方案在 13 人合照里仍压到最左/最右后排人物额头（用户实测），故移到底部。
        # 右下：角色台词 / 左下：旁白（v2.11：短句走场景形状池，长句用两角矩形框）
        if len(a.t1) <= 14:
            a._boxes.append(draw_fancy_bubble(img, W, H, a.t1, seed=(a.seed or 0) + 5,
                                              scene=a.scene, corner='br',
                                              max_w_frac=0.24, max_h_frac=0.13, tail='top'))
            a._shapes.append(draw_fancy_bubble.last['shape'])
        else:
            a._boxes.append(draw_h_bubble(draw, W, H, (int(0.63 * W), int(0.83 * H),
                                                      int(0.34 * W), int(0.14 * H)), a.t1, f1))
            a._shapes.append('h_bubble')
        if len(a.t2) <= 14:
            a._boxes.append(draw_fancy_bubble(img, W, H, a.t2, seed=(a.seed or 0) + 9,
                                              scene=a.scene, corner='bl',
                                              max_w_frac=0.20, max_h_frac=0.10, tail='top'))
            a._shapes.append(draw_fancy_bubble.last['shape'])
        else:
            a._boxes.append(draw_h_bubble(draw, W, H, (int(0.02 * W), int(0.85 * H),
                                                      int(0.28 * W), int(0.12 * H)), a.t2, f2))
            a._shapes.append('h_bubble')
        if word:
            sf = rt.load_font(TITLE_FONT, int(min(W, H) * 0.062))
            rt.draw_sfx(draw, int(0.86 * W), int(0.30 * H), word, sf,
                        'black', 'white', pick_sfx_style(word), seed=3)
    else:
        # v2.9.4：未显式传脸框时，自动检测人脸用于避让
        if not (a.fx0 and a.fx1 and a.fy0 and a.fy1):
            _fd = _detect_face_box(img)
            # 只有人脸面积占画面 >10% 才算「主体人像」；否则视为误检（宠物/背景路人），走角落布局
            if _fd and (_fd[2] - _fd[0]) * (_fd[3] - _fd[1]) > 0.10 * W * H:
                a.fx0, a.fy0, a.fx1, a.fy1 = _fd
        # 脸信息（缺省则按居中假设）
        if a.fy0 and a.fy1:
            cy = (a.fy0 + a.fy1) // 2
            fy0, fy1 = a.fy0, a.fy1
        else:
            cy = int(0.30 * H)
            fy0, fy1 = int(0.28 * H), int(0.60 * H)
        if a.fx0 and a.fx1:
            fx0, fx1 = a.fx0, a.fx1
        else:
            fx0, fx1 = int(0.38 * W), int(0.62 * W)
        face_provided = bool(a.fx0 and a.fx1 and a.fy0 and a.fy1)
        random.seed(a.seed if a.seed else None)
        # 对话框避让铁律（v2.8.1 修复压脸/压背景文字）：
        # 提供脸框 → 放脸框对角贴边（脸偏左→右、脸偏上→下）；合照/多人脸分散统一落底部两角避脸。
        if face_provided:
            face_cx = (fx0 + fx1) / 2.0
            face_cy = (fy0 + fy1) / 2.0
            side = 'right' if face_cx <= 0.5 * W else 'left'
            vert = 'bottom' if face_cy <= 0.5 * H else 'top'
            cy = int(0.78 * H) if vert == 'bottom' else int(0.22 * H)
            cx = int(0.80 * W) if side == 'right' else int(0.20 * W)
            tail_dir = 'left' if side == 'right' else 'right'
            # v2.11：短台词走「场景形状池 + 台词触发」，与脸对角贴角（天然不压脸）；
            # 长台词才用竖排胶囊（可读性优先）。这样对话框形状不再千篇一律一个椭圆。
            if len(a.t1) <= 14:
                _corner = ('b' if vert == 'bottom' else 't') + ('r' if side == 'right' else 'l')
                main_box = draw_fancy_bubble(img, W, H, a.t1, seed=(a.seed or 0) + 3,
                                             scene=a.scene, corner=_corner,
                                             max_w_frac=0.24, max_h_frac=0.14,
                                             tail=('top' if vert == 'bottom' else 'bottom'))
                a._shapes.append(draw_fancy_bubble.last['shape'])
            else:
                main_box = draw_v_bubble(draw, W, H, cx, cy, a.t1, tail_dir=tail_dir)
                a._shapes.append('v_bubble')
            layout = 'custom'
        elif a.scene in ('people',):
            if a.layout != 'auto':
                layout = a.layout
            else:
                face_cx = (fx0 + fx1) / 2.0
                layout = 'v_left' if face_cx >= 0.5 * W else 'v_right'
        else:
            layout = a.layout if a.layout != 'auto' else \
                random.choice(['v_right', 'v_left'])

        # v2.9.4：横图且无明确人脸（风景/群像/宠物）→ 走角落布局，只占画面一角，不挡中心
        if not face_provided and W > H * 1.12 and a.layout == 'auto':
            layout = 'corner'

        if layout == 'corner':
            # v2.9.6：触发形状 + 自适应字号 + 贴角夹取（框绝不越界）
            main_box = draw_fancy_bubble(img, W, H, a.t1,
                                         seed=(a.seed or 0) + 11, scene=a.scene)
        elif layout in ('v_right', 'v_left', 'h_top', 'h_bottom'):
            main_box = None
            if layout == 'v_right':
                cx = W - int(W * 0.13)
                main_box = draw_v_bubble(draw, W, H, cx, cy, a.t1, tail_dir='left')
            elif layout == 'v_left':
                cx = int(W * 0.13)
                main_box = draw_v_bubble(draw, W, H, cx, cy, a.t1, tail_dir='right')
            elif layout == 'h_top':
                half = _est_bubble_half(draw, a.t1, W)
                pad = max(4, int(W * 0.006)) + int(W * 0.012)
                cx, cy = int(0.50 * W), max(int(0.13 * H), int(H * 0.05) + int(half) + pad)
                main_box = draw_from_library(draw, W, H, cx, cy, a.t1, a.scene, a.seed,
                                             forbid=['bottom', 'bl', 'br'])
            elif layout == 'h_bottom':
                half = _est_bubble_half(draw, a.t1, W)
                pad = max(4, int(W * 0.006)) + int(W * 0.012)
                cx, cy = int(0.50 * W), min(int(0.87 * H), H - (int(H * 0.05) + int(half) + pad))
                main_box = draw_from_library(draw, W, H, cx, cy, a.t1, a.scene, a.seed,
                                             forbid=['top', 'tl', 'tr'])
        # v2.9.7：统一越界兜底——任何布局产出的框若超出画布，改用自适应贴角气泡重画
        if main_box:
            _bx0, _by0, _bx1, _by1 = main_box
            if _bx0 < 0 or _by0 < 0 or _bx1 > W or _by1 > H:
                main_box = draw_fancy_bubble(img, W, H, a.t1,
                                             seed=(a.seed or 0) + 11, scene=a.scene)
                layout = 'corner'
        # layout=='custom'（face_provided 已直接设 main_box）跳过
        if main_box:
            a._boxes.append(tuple(int(v) for v in main_box))   # v2.10：供情绪符号避让


        # 各布局下不会压脸的安全唰位集合（auto 时从中随机）
        SAFE = {
            'v_right':  ['down', 'up', 'left', 'right', 'diag'],
            'v_left':   ['down', 'up', 'right', 'diag'],
            'h_top':    ['down', 'diag'],
            'h_bottom': ['up', 'diag'],
        }
        sp = a.sfx_pos if a.sfx_pos not in ('auto', 'none') else \
            random.choice(SAFE.get(layout, ['down', 'up', 'left', 'right', 'diag']))
        sfx_box = None
        if word and sp != 'none' and main_box:
            mx0, my0, mx1, my1 = main_box
            mcx, mcy = (mx0 + mx1) // 2, (my0 + my1) // 2
            sf = rt.load_font(TITLE_FONT, int(min(W, H) * 0.058))
            _sfx_style = pick_sfx_style(word)
            # SFX（burst）实际半宽≈tw/2+0.55·size、半高≈1.4·size；估算框略放大并加 margin 兜底
            sw = int(draw.textlength(word, font=sf)) + int(W * 0.08)
            sh = int(W * 0.05)
            margin = int(W * 0.02)

            # 八向候选：先夹进画布内，再用于重叠判定（避免“夹取后掉进对话框”）
            def clamp_pt(p):
                return (min(max(p[0], int(W * 0.10)), int(W * 0.90)),
                        min(max(p[1], int(H * 0.08)), int(H * 0.92)))
            ry = (my1 - my0) / 2 + sh * 0.6 + int(H * 0.03)
            rx = (mx1 - mx0) / 2 + sw * 0.6 + int(W * 0.03)
            cands = {k: clamp_pt(v) for k, v in {
                'down':  (mcx, my1 + ry), 'up': (mcx, my0 - ry),
                'left':  (mx0 - rx, mcy),  'right': (mx1 + rx, mcy),
                'diag':  (mx1 + rx * 0.7, my1 + ry * 0.7),
            }.items()}

            # 重叠判定拆两条：对话框（硬性禁止）、脸（仅“显式提供脸范围”时才软性避让，
            # 默认居中猜测不准，绝不允许为了它把语气词塞进对话框）
            def hit_bubble(sx, sy):
                return not (sx + sw / 2 < mx0 - margin or sx - sw / 2 > mx1 + margin or
                            sy + sh / 2 < my0 - margin or sy - sh / 2 > my1 + margin)
            def hit_face(sx, sy):
                return face_provided and not (
                    sx + sw / 2 < fx0 - margin or sx - sw / 2 > fx1 + margin or
                    sy + sh / 2 < fy0 - margin or sy - sh / 2 > fy1 + margin)

            order = [sp] if sp != 'auto' else SAFE.get(
                layout, ['down', 'up', 'left', 'right', 'diag'])
            for d in ['down', 'up', 'left', 'right', 'diag']:
                if d not in order:
                    order.append(d)   # 兜底：所有方向都试一遍

            # 优先“既避气泡又避脸”；其次“仅避气泡”（绝不允许压在对话框上）
            good, ok = [], []
            for d in order:
                c = cands.get(d)
                if not c or hit_bubble(*c):
                    continue
                (ok if hit_face(*c) else good).append(c)
            sx, sy = (good or ok or [clamp_pt((mcx, my1 + ry + int(H * 0.05)))])[0]
            rt.draw_sfx(draw, sx, sy, word, sf, 'black', 'white', _sfx_style,
                        seed=random.randint(1, 99))
            sfx_box = (sx - sw // 2, sy - sh // 2, sx + sw // 2, sy + sh // 2)

    # ---------- 情绪符号层（v2.10）：最后一层，自动避让脸/框/画布 ----------
    _sym_names = []
    if getattr(a, 'emotion', 'auto') not in ('none', '', None):
        if a.emotion == 'auto':
            _sym_names = symlib.pick_for_text((a.t1 or '') + (a.t2 or ''), a.scene, allow_dark=a.dark)
        else:
            _sym_names = [x.strip() for x in a.emotion.split(',') if x.strip()]
            _bad = [x for x in _sym_names if x not in symlib.ALL]
            if _bad:
                sys.exit('[comic_story] 未知情绪符号: %s（可选: %s）' % (','.join(_bad),
                                                                  ','.join(sorted(symlib.ALL))))
            if any(x in symlib.DARK for x in _sym_names) and not a.dark:
                sys.stderr.write('[comic_story] 提示：%s 属黑化派符号，已按显式指定绘制\n'
                                 % ','.join(x for x in _sym_names if x in symlib.DARK))
    _placed = []
    if _sym_names:
        _face = (a.fx0, a.fy0, a.fx1, a.fy1) if (a.fx0 and a.fx1 and a.fy0 and a.fy1) else None
        _layer, _placed = symlib.place_layer(img.size, _sym_names, face=_face,
                                        avoid=list(getattr(a, '_boxes', [])), seed=a.seed)
        img.alpha_composite(_layer)

    img.save(a.output)
    print('[ok]', a.output, 'size', W, H, '| mode=', a.mode,
          '| sfx=', (word if word else 'none'))
    print('[report] ' + json.dumps({'report': True, 'mode': a.mode, 'scene': a.scene,
                      'shapes': a._shapes,
                      'symbols': _sym_names, 'symbol_boxes': [[int(v) for v in b] for b in _placed],
                      'speedlines': bool(a.speedlines),
                      'ambient': bool(getattr(a, '_ambient_drawn', False)),
                      'sfx': (word if word else 'none'),
                      'main_box': list(main_box) if main_box else None,
                      'sfx_box': list(sfx_box) if sfx_box else None},
                     ensure_ascii=False))


# ===== 照片感知动效引擎（v2.8.5）=====
# 原则：动效不套固定模板，而是「读图 → 定调 → 渲染」。
# perceive_photo 提取照片暖冷/亮度/边缘活跃度；decide_ambient 综合 scene+情绪词+感知决策语言；
# draw_ambient 按语言渲染「融入照片的高级氛围」（柔光晕+白S弧气流+星尘，半透明渐隐，拒卡通符号）。

def perceive_photo(img):
    """轻量像素感知：返回 {warmth, brightness, edge_activity}"""
    try:
        small = img.resize((90, max(1, int(90 * img.height / img.width))))
    except Exception:
        small = img.resize((90, 90))
    px = list(small.convert('RGB').getdata())
    n = len(px) or 1
    sr = sg = sb = 0
    for (r, g, b) in px:
        sr += r; sg += g; sb += b
    ar, ag, ab = sr / n, sg / n, sb / n
    warmth = (ar - ab) / 255.0
    brightness = (ar + ag + ab) / (3 * 255.0)
    gray = small.convert('L')
    gw, gh = gray.size
    gpx = list(gray.getdata())
    act = 0.0; cnt = 0
    for y in range(1, gh):
        base = y * gw
        for x in range(1, gw):
            i = base + x
            d = abs(gpx[i] - gpx[i - 1]) + abs(gpx[i] - gpx[i - gw])
            act += d * d; cnt += 1
    edge_activity = math.sqrt(act / cnt) / 255.0 if cnt else 0.0
    return {'warmth': warmth, 'brightness': brightness, 'edge_activity': edge_activity}


MOTION_KW = ['跑','跳','绳','运','疯','飞','冲刺','活力','运动','舞','浪','冲','滑','跃','球','骑','竞','赛','挥','击','踢','蹦','奔']


def decide_ambient(img, scene, t1, t2, seed, mode='single'):
    """按照片感知 + scene + 情绪词决策动效语言。返回 dict(lang, warmth, ...)。"""
    p = perceive_photo(img) if img is not None else {'warmth': 0.0, 'brightness': 0.5, 'edge_activity': 0.1}
    txt = (t1 or '') + (t2 or '')
    motion = (scene == 'sport') or any(k in txt for k in MOTION_KW)
    if motion:
        return {'lang': 'speedlines', 'warmth': p['warmth']}
    if scene in ('food', '美食'):
        lang = 'food'
    elif scene in ('city', 'street', 'night', '城市', '夜景', '街'):
        lang = 'city'
    elif scene in ('pet', 'kid', '宠物', '亲子'):
        lang = 'pet'
    elif scene in ('nature', '自然', '风光', '风景', '户外', '旅行', '海边', '林', '山', '花', '草'):
        lang = 'nature'
    elif scene in ('people',):
        lang = 'warm' if (mode == 'double' or p['warmth'] < -0.03) else 'zen'
    else:
        lang = 'zen'
    return {'lang': lang, 'warmth': p['warmth'], 'brightness': p['brightness'], 'edge_activity': p['edge_activity']}


def _aura_glow_field(W, H, cx, cy, lang, rng):
    """柔光气场强度场（灰度 0..255）。设计：①主体外围的环形背光晕（峰值在主体边缘外，
    像背后打光的 halo）②整体柔光随距离衰减 ③环绕主体的几团柔'气'光斑。最后高斯模糊成真柔边。"""
    base_r = min(W, H) * (0.62 if lang in ('zen', 'warm') else 0.52)
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r0 = base_r * 0.46
    sigma = base_r * 0.30
    ring = np.exp(-((d - r0) / sigma) ** 2)
    general = np.clip(1.0 - d / (base_r * 1.15), 0, 1) ** 1.3
    field = np.clip(0.70 * ring + 0.55 * general, 0, 1)
    glow = Image.fromarray((field * 255).astype(np.uint8), mode='L')
    glow = glow.filter(ImageFilter.GaussianBlur(max(16, int(min(W, H) * 0.075))))
    blobs = Image.new('L', (W, H), 0)
    bd = ImageDraw.Draw(blobs)
    nblobs = {'zen': 5, 'warm': 4, 'nature': 6, 'food': 4, 'pet': 4, 'city': 4}.get(lang, 4)
    for _ in range(nblobs):
        ang = rng.uniform(0, 2 * math.pi)
        dist = min(W, H) * rng.uniform(0.22, 0.46)
        bx = cx + math.cos(ang) * dist
        by = cy + math.sin(ang) * dist * 0.85
        br = min(W, H) * rng.uniform(0.10, 0.20)
        bd.ellipse([bx - br, by - br, bx + br, by + br], fill=rng.randint(130, 210))
    blobs = blobs.filter(ImageFilter.GaussianBlur(max(22, int(min(W, H) * 0.10))))
    glow_np = np.maximum(np.array(glow, dtype=np.float32), np.array(blobs, dtype=np.float32))
    return Image.fromarray(np.clip(glow_np, 0, 255).astype(np.uint8), mode='L')

def _soft_stardust(W, H, lang, rng, keepout):
    """少量柔光星尘（加亮混合的辉光小点，非硬白点），绕开主体。"""
    n = {'zen': 9, 'warm': 7, 'nature': 8, 'food': 6, 'pet': 7, 'city': 10}.get(lang, 7)
    layer = Image.new('RGB', (W, H), (0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for _ in range(n):
        x = rng.uniform(W * 0.06, W * 0.94)
        y = rng.uniform(H * 0.08, H * 0.92)
        if keepout and (keepout[0] <= x <= keepout[2] and keepout[1] <= y <= keepout[3]):
            continue
        r = min(W, H) * rng.uniform(0.004, 0.009)
        ld.ellipse([x - r * 3, y - r * 3, x + r * 3, y + r * 3], fill=(70, 70, 70))
        ld.ellipse([x - r, y - r, x + r, y + r], fill=(200, 200, 200))
    layer = layer.filter(ImageFilter.GaussianBlur(max(3, int(min(W, H) * 0.006))))
    return layer


def _motion_streak(ld, x0, y0, dx, dy, width, intensity):
    """画一段拉长的运动线（线清晰、头部小），读作方向性运动而非静态圆斑。"""
    x1, y1 = x0 + dx, y0 + dy
    ld.line([x0, y0, x1, y1], fill=intensity, width=max(2, int(width)))
    r = max(1.2, width * 1.15)
    ld.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=int(intensity))


def _draw_motion(W, H, lang, warmth, rng, center, keepout, base_lum=None):
    """场景化动效（动态/运动感）：方向成组、可读作飘落/升腾/流动，非散乱弧线。
    落点避开过亮背景区（base_lum>=195），使动效自然落在暗部/前景，screen 发光跳出。"""
    layer = Image.new('L', (W, H), 0)
    ld = ImageDraw.Draw(layer)
    mw = min(W, H)

    def pick(x0, x1, y0, y1):
        for thr in (215, 235, 256):
            for _ in range(7):
                x = rng.uniform(x0, x1) * W
                y = rng.uniform(y0, y1) * H
                if base_lum is None:
                    return x, y
                yi = min(H - 1, max(0, int(y)))
                xi = min(W - 1, max(0, int(x)))
                if base_lum[yi, xi] < thr:
                    return x, y
        return x, y

    if lang == 'food':
        n = rng.randint(4, 6)
        for _ in range(n):
            x, y = pick(0.18, 0.82, 0.05, 0.55)
            segs = rng.randint(3, 5); px, py = x, y
            for s in range(segs):
                dy = -mw * rng.uniform(0.05, 0.10)
                dx = rng.uniform(-0.035, 0.035) * W
                w = max(3, int(mw * rng.uniform(0.008, 0.013)))
                _motion_streak(ld, px, py, dx, dy, w, rng.randint(170, 225))
                px += dx; py += dy
    elif lang == 'nature':
        n = rng.randint(9, 13)
        for _ in range(n):
            x, y = pick(0.06, 0.94, 0.0, 0.62)
            dy = mw * rng.uniform(0.09, 0.17)
            dx = rng.uniform(-0.05, 0.05) * W
            w = max(3, int(mw * rng.uniform(0.006, 0.011)))
            _motion_streak(ld, x, y, dx, dy, w, rng.randint(165, 220))
    elif lang == 'city':
        n = rng.randint(8, 12)
        for _ in range(n):
            x, y = pick(0.05, 0.72, 0.10, 0.92)
            dx = (mw * rng.uniform(0.22, 0.42)) * (1 if rng.random() < 0.7 else -1)
            dy = rng.uniform(-0.02, 0.02) * H
            w = max(3, int(mw * rng.uniform(0.005, 0.009)))
            _motion_streak(ld, x, y, dx, dy, w, rng.randint(160, 215))
    else:
        n = rng.randint(8, 12)
        for _ in range(n):
            x, y = pick(0.08, 0.92, 0.25, 0.92)
            dy = -mw * rng.uniform(0.07, 0.15)
            dx = rng.uniform(-0.04, 0.04) * W
            w = max(3, int(mw * rng.uniform(0.005, 0.009)))
            _motion_streak(ld, x, y, dx, dy, w, rng.randint(160, 215))
    if keepout:
        km = Image.new('L', (W, H), 255)
        ImageDraw.Draw(km).rectangle([keepout[0], keepout[1], keepout[2], keepout[3]], fill=0)
        km = km.filter(ImageFilter.GaussianBlur(max(18, int(mw * 0.07))))
        arr = np.array(layer, dtype=np.float32) * (np.array(km, dtype=np.float32) / 255.0)
        layer = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode='L')
    layer = layer.filter(ImageFilter.GaussianBlur(max(1, int(mw * 0.0018))))
    return layer
def draw_ambient(draw, W, H, lang, params, seed, base_img=None):
    """按动效语言渲染'融入照片的高级柔光气场'（背光+白气环绕+少量星尘）。
    关键技术：采用 screen（加亮）混合，使发光晕在亮/暗背景上都可见；并加中央 keepout
    避免光斑压住主体。speedlines 由 draw_speedlines 处理。返回 bool。"""
    if lang == 'speedlines':
        return False
    rng = random.Random(seed)
    warmth = params.get('warmth', 0.0)
    center = params.get('center', (W / 2.0, H * 0.42))
    keepout = params.get('keepout', None)
    if keepout is None:
        hr = int(min(W, H) * 0.20); vr = int(min(W, H) * 0.26)
        keepout = (int(center[0] - hr), int(center[1] - vr),
                   int(center[0] + hr), int(center[1] + vr))
    cx, cy = center
    if warmth > 0.03:
        tint = (255, 224, 170)
    elif warmth < -0.03:
        tint = (196, 220, 255)
    else:
        tint = (255, 238, 218)
    target = base_img if base_img is not None else getattr(draw, '_image', None)
    if target is None:
        return True
    base_rgb = target.convert('RGB')
    glow = _aura_glow_field(W, H, cx, cy, lang, rng)
    if keepout:
        km = Image.new('L', (W, H), 255)
        kd = ImageDraw.Draw(km)
        kd.rectangle([keepout[0], keepout[1], keepout[2], keepout[3]], fill=0)
        km = km.filter(ImageFilter.GaussianBlur(max(20, int(min(W, H) * 0.08))))
        glow_np = np.array(glow.convert('L'), dtype=np.float32) * (np.array(km, dtype=np.float32) / 255.0)
    else:
        glow_np = np.array(glow.convert('L'), dtype=np.float32)
    dust = _soft_stardust(W, H, lang, rng, keepout)
    dust_np = np.array(dust.convert('L'), dtype=np.float32)
    base_lum = np.array(base_rgb, dtype=np.float32).mean(axis=2)
    motion = _draw_motion(W, H, lang, warmth, rng, center, keepout, base_lum)
    motion_np = np.array(motion.convert('L'), dtype=np.float32)
    tint_arr = np.array(tint, dtype=np.float32)
    # 单层：氛围作底（略压），动效权重提高 -> 拖尾比氛围更亮，读出方向性运动
    garr = np.clip(glow_np * 0.75 + dust_np + motion_np * 1.7, 0, 255)
    alpha = np.clip(garr * 0.95, 0, 255).astype(np.uint8)
    light_rgb = np.clip((garr / 255.0)[..., None] * tint_arr[None, None, :], 0, 255).astype(np.uint8)
    light_img = Image.fromarray(light_rgb, mode='RGB')
    base_arr = np.array(base_rgb, dtype=np.float32)
    base_lum = base_arr.mean(axis=2)
    screen_arr = np.array(ImageChops.screen(base_rgb, light_img), dtype=np.float32)
    a03 = alpha.astype(np.float32) / 255.0
    over_arr = light_rgb.astype(np.float32) * a03[..., None] + base_arr * (1.0 - a03[..., None])
    dark = base_lum < 200
    out_arr = np.where(dark[..., None], screen_arr, over_arr)
    out = Image.fromarray(out_arr.astype(np.uint8), mode='RGB')
    target.paste(out.convert('RGBA'), (0, 0))
    if os.environ.get('CS_DUMP_MOTION'):
        _tag = os.environ.get('CS_DUMP_TAG', 'x')
        _d = os.environ.get('CS_DUMP_DIR', './output')
        motion.save(os.path.join(_d, 'motion_%s.png' % _tag))
    return True


# ===== 静态场景动效：贴剪影的立体环绕风线 + 星芒（v2.8.6 新增；7794 禅坐认证样式）=====
def _sw_grabcut_mask(rgb_img, rect_frac):
    """GrabCut 抠人物剪影；cv2 缺失/失败回退为中心矩形。"""
    arr = np.array(rgb_img.convert('RGB'))
    Hh, Ww = arr.shape[:2]
    x0 = int(rect_frac[0] * Ww); y0 = int(rect_frac[1] * Hh)
    x1 = int((rect_frac[0] + rect_frac[2]) * Ww); y1 = int((rect_frac[1] + rect_frac[3]) * Hh)
    try:
        import cv2 as _cv
    except Exception:
        _cv = None
    if _cv is None:
        m = np.zeros((Hh, Ww), np.uint8); m[y0:y1, x0:x1] = 1
        return m
    bgr = _cv.cvtColor(arr, _cv.COLOR_RGB2BGR)
    mask = np.zeros((Hh, Ww), np.uint8)
    bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
    try:
        _cv.grabCut(bgr, mask, (x0, y0, max(8, x1 - x0), max(8, y1 - y0)), bgd, fgd, 5,
                    _cv.GC_INIT_WITH_RECT)
        m = np.where((mask == 2) | (mask == 0), 0, 1).astype(np.uint8)
        m = _cv.morphologyEx(m, _cv.MORPH_CLOSE, np.ones((13, 13), np.uint8))
        m = _cv.morphologyEx(m, _cv.MORPH_OPEN, np.ones((7, 7), np.uint8))
        if m.mean() < 0.02:
            raise RuntimeError('mask too small')
    except Exception:
        m = np.zeros((Hh, Ww), np.uint8); m[y0:y1, x0:x1] = 1
    return m


def _sw_body_profile(m):
    """从剪影提取每行左右边界 -> (half, cx, ytop, ybot)，并做平滑。"""
    Hh, Ww = m.shape
    half = np.zeros(Hh); cxr = np.zeros(Hh)
    ys = []
    for y in range(Hh):
        xs = np.where(m[y] > 0)[0]
        if len(xs) > 5:
            half[y] = (xs.max() - xs.min()) / 2.0
            cxr[y] = (xs.max() + xs.min()) / 2.0
            ys.append(y)
    k = 15
    ker = np.ones(k) / k
    half = np.convolve(half, ker, mode='same')
    cxr = np.convolve(cxr, ker, mode='same')
    if not ys:
        return half, cxr, int(Hh * 0.15), int(Hh * 0.85)
    ys = np.array(ys)
    return half, cxr, int(np.percentile(ys, 3)), int(np.percentile(ys, 97))


def _sw_glow(W, H, cx, cy, r, color, peak, power=1.8):
    """人物背后的径向柔光晕（真柔边）。"""
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    f = np.clip(1 - d / max(1.0, r), 0, 1) ** power
    arr = np.zeros((H, W, 4), np.uint8)
    arr[..., 0] = color[0]; arr[..., 1] = color[1]; arr[..., 2] = color[2]
    arr[..., 3] = (f * peak).astype(np.uint8)
    return Image.fromarray(arr).filter(ImageFilter.GaussianBlur(max(2, int(r * 0.24))))


def _sw_star_dust(W, H, n_total=14, seed=807, color=(255, 240, 215)):
    """807 样图式星芒光尘：小点 / 十字 / 六角 三档，四区域分布（头/左/右/膝前）。"""
    rng = random.Random(seed)
    L = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(L)

    def _star(cx, cy, r, kind, alpha):
        if kind == 'dot':
            d.ellipse([cx - r * .7, cy - r * .7, cx + r * .7, cy + r * .7],
                      fill=(color[0], color[1], color[2], alpha))
        elif kind == 'cross':
            ang0 = rng.uniform(0, math.pi)
            for ang in (ang0, ang0 + math.pi / 2):
                dx, dy = math.cos(ang), math.sin(ang)
                d.line([cx - dx * r * 1.8, cy - dy * r * 1.8,
                        cx + dx * r * 1.8, cy + dy * r * 1.8],
                       fill=(color[0], color[1], color[2], alpha), width=max(1, int(r * .4)))
        else:
            a0 = rng.uniform(0, math.pi); pts = []
            for k in range(12):
                ang = a0 + k * math.pi / 6
                rr = r * 1.3 if k % 2 == 0 else r * .55
                pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
            d.polygon(pts, fill=(color[0], color[1], color[2], alpha))

    for x0, x1, y0, y1, n, sz in [
        (.35, .70, .06, .28, 5, (.004, .008)),
        (.05, .25, .30, .60, 4, (.003, .006)),
        (.70, .92, .35, .70, 4, (.004, .007)),
        (.30, .70, .78, .94, 3, (.006, .010)),
    ]:
        for _ in range(n):
            x = rng.uniform(x0, x1) * W; y = rng.uniform(y0, y1) * H
            _star(x, y, rng.uniform(*sz) * min(W, H), rng.choice(['dot', 'cross', 'hex']),
                  rng.randint(170, 235))
    return L.filter(ImageFilter.GaussianBlur(max(1, int(min(W, H) * .0018))))


def draw_swirl_wind(draw, W, H, base_img=None, n_arcs=5, color=(255, 250, 236),
                    glow_color=(255, 236, 198), seed=1234, star=True,
                    rect=(0.18, 0.12, 0.64, 0.82), glow_cy=0.18):
    """【静态场景专用·环绕风】贴真实剪影的立体环绕风线（GrabCut + 螺旋缠绕 + 前后遮挡）。

    适用：禅意/静坐/端庄/站立演讲等"主体静止但要有气息流动"的画面。
    - 用 GrabCut 抠出人物剪影，按每行左右边界让风线贴着真实身形起伏缠绕（非同心圆）
    - sin(theta) 分前(覆盖人物,较亮) / 后(被剪影遮挡,较淡)，产生"从身前绕到身后"的立体感
    - 多圈(默认5)、细线、大发光柔边、两端渐隐
    - star=True 时叠 807 式星芒光尘
    返回 True（已绘制）/ False（无底图）。
    """
    target = base_img if base_img is not None else getattr(draw, '_image', None)
    if target is None:
        return False
    rng = random.Random(seed)
    m = _sw_grabcut_mask(target, rect)
    half, cxr, ytop, ybot = _sw_body_profile(m)
    mw = min(W, H)
    out = target.convert('RGBA')
    out = Image.alpha_composite(out, _sw_glow(W, H, 0.5 * W, glow_cy * H, mw * 0.40,
                                              glow_color, 120))
    front = Image.new('RGBA', (W, H), (0, 0, 0, 0)); fd = ImageDraw.Draw(front)
    back = Image.new('RGBA', (W, H), (0, 0, 0, 0)); bd = ImageDraw.Draw(back)
    span = max(1, ybot - ytop)
    for i in range(n_arcs):
        turns = rng.uniform(1.3, 2.3)
        phase = i * (2 * math.pi / n_arcs) + rng.uniform(-0.25, 0.25)
        y0 = ytop + rng.uniform(0.0, 0.16) * span
        y1 = y0 + rng.uniform(0.5, 0.9) * span
        pts = []
        for t in np.linspace(0, 1, 140):
            y = y0 + (y1 - y0) * t
            yi = int(np.clip(y, 0, H - 1))
            hw = half[yi]
            if hw <= 2:
                continue
            th = phase + turns * 2 * math.pi * t
            pts.append((cxr[yi] + math.cos(th) * hw * 1.12, y, math.sin(th), t))
        if len(pts) < 3:
            continue
        for k in range(len(pts) - 1):
            x0, ya, z0, _ = pts[k]; x1, yb, z1, _ = pts[k + 1]
            env = math.sin(math.pi * (0.1 + 0.8 * (k / (len(pts) - 1))))
            wc = max(1, int((1 - 0.35 * (k / (len(pts) - 1))) * mw * 0.0017) + 1)
            if (z0 + z1) >= 0:
                fd.line([(x0, ya), (x1, yb)], fill=(color[0], color[1], color[2],
                                                   int(135 * env)), width=wc)
            else:
                bd.line([(x0, ya), (x1, yb)], fill=(color[0], color[1], color[2],
                                                   int(80 * env)), width=wc)
    fglow = front.filter(ImageFilter.GaussianBlur(mw * 0.009))
    bglow = back.filter(ImageFilter.GaussianBlur(mw * 0.009))
    pmsk = np.array(Image.fromarray((m * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(mw * 0.010)), dtype=np.float32) / 255.0
    for img in (back, bglow):
        arr = np.array(img, dtype=np.float32); arr[..., 3] *= (1.0 - pmsk)
        img.paste(Image.fromarray(arr.astype(np.uint8)), (0, 0))
    for L in (bglow, back, fglow, front):
        out = Image.alpha_composite(out, L)
    if star:
        out = Image.alpha_composite(out, _sw_star_dust(W, H, 14, seed=seed + 1))
    target.paste(out.convert('RGBA'), (0, 0))
    return True



# ===== 风效库：gust 吹过风 / spiral 旋绕风（v2.8.8；据原厂参考复刻）=====
def _w_catmull(points, sps=28):
    """Catmull-Rom 平滑插值。"""
    P = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, sps, endpoint=False):
            t2 = t * t; t3 = t2 * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(points[-1])
    return out


def _w_taper(dr, pts, w0, w1, a0, a1, col):
    """锥形线：宽度 w0→w1、透明度 a0→a1，末端自然尖细消失。"""
    n = len(pts)
    for i in range(n - 1):
        t = i / max(1, n - 1)
        w = max(1, int(round(w0 + (w1 - w0) * t)))
        a = int(a0 + (a1 - a0) * t)
        if a <= 2:
            continue
        dr.line([pts[i], pts[i + 1]], fill=(col[0], col[1], col[2], a), width=w)


def _w_offset(pts, off):
    """沿曲线法向整体平移（做平行成组）。"""
    out = []
    for j in range(len(pts)):
        j0 = max(0, j - 1); j1 = min(len(pts) - 1, j + 1)
        tx = pts[j1][0] - pts[j0][0]; ty = pts[j1][1] - pts[j0][1]
        ln = math.hypot(tx, ty) or 1.0
        out.append((pts[j][0] - ty / ln * off, pts[j][1] + tx / ln * off))
    return out


def _w_leaf(dr, x, y, size, ang, fill, edge, width_scale=1.0):
    """极简叶片：卵形轮廓 + 主脉 + 侧脉 + 叶柄。"""
    pts_l, pts_r = [], []
    for t in np.linspace(0, 1, 14):
        w = size * 0.34 * (math.sin(math.pi * t) ** 0.85)
        pts_l.append((w, -size * 0.9 * t))
        pts_r.append((-w, -size * 0.9 * t))
    poly = []
    for _px, _py in pts_l + pts_r[::-1]:
        _rx, _ry = _rot(_px, _py, ang)
        poly.append((x + _rx, y + _ry))
    dr.polygon(poly, fill=fill, outline=edge)
    tip = _rot(0, -size * 0.9, ang); base = _rot(0, size * 0.12, ang)
    dr.line([(x + base[0], y + base[1]), (x + tip[0], y + tip[1])], fill=edge,
            width=max(1, int(size * 0.05 * width_scale)))
    for k in range(3):
        tt = 0.25 + 0.2 * k
        wv = size * 0.3 * math.sin(math.pi * tt)
        for sgn in (1, -1):
            a = _rot(0, -size * 0.9 * tt, ang); b = _rot(sgn * wv, -size * 0.9 * (tt + 0.1), ang)
            dr.line([(x + a[0], y + a[1]), (x + b[0], y + b[1])], fill=edge,
                    width=max(1, int(size * 0.03 * width_scale)))


def _rot(px, py, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (px * c - py * s, px * s + py * c)


def draw_wind_gust(draw, W, H, base_img=None, seed=808, n_parallel=3,
                   leaves=True, color=None):
    """【吹过风 gust】复刻原厂「簌簌」风效：
    左侧 3 条平行 S 形曲线（起始粗→末端尖细消失、恒定间距，贴人物左侧空间不接触身体）
    + 右肩后 1 条短微弧（等粗、钝头）+ 可选 2 片飘叶。
    线条颜色按背景自动（亮背景深灰黑 / 暗背景白）。"""
    target = base_img if base_img is not None else getattr(draw, '_image', None)
    if target is None:
        return False
    rng = random.Random(seed)
    if color is None:
        lum = np.array(target.convert('L'), dtype=np.float32).mean()
        color = (38, 38, 38) if lum > 140 else (250, 250, 250)
    L = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(L)

    # —— 主风：3 条平行 S 形（左上 → 左下，S 形大弯）——
    base_kp = [(0.155, 0.44), (0.115, 0.52), (0.100, 0.60), (0.075, 0.70),
               (0.052, 0.80), (0.045, 0.88)]
    base_path = _w_catmull([(x * W, y * H) for x, y in base_kp], 26)
    gap = min(W, H) * 0.016
    w0 = max(2, int(min(W, H) * 0.0038))
    for i in range(n_parallel):
        off = (i - (n_parallel - 1) / 2.0) * gap
        pts = _w_offset(base_path, off)
        _w_taper(d, pts, w0, 1, 215, 18, color)

    # —— 辅风：右肩后 1 条短微弧（等粗钝头）——
    aux_kp = [(0.795, 0.345), (0.845, 0.395), (0.890, 0.455), (0.925, 0.505)]
    aux = _w_catmull([(x * W, y * H) for x, y in aux_kp], 24)
    for j in range(len(aux) - 1):
        t = j / max(1, len(aux) - 1)
        a = int(190 * (1 - t * 0.55))
        d.line([aux[j], aux[j + 1]], fill=(color[0], color[1], color[2], a),
               width=max(2, int(min(W, H) * 0.0022)))

    # —— 飘叶 2 片（在风线旁，随风向）——
    if leaves:
        for k, (lx, ly, sz) in enumerate([(0.152, 0.60, 0.030), (0.205, 0.755, 0.026)]):
            _w_leaf(d, lx * W, ly * H, min(W, H) * sz,
                    math.radians(35 + 20 * k),
                    (126, 186, 96, 235), (58, 110, 52, 245))
    target.paste(Image.alpha_composite(target.convert('RGBA'), L).convert('RGBA'), (0, 0))
    return True


def draw_wind_spiral(draw, W, H, base_img=None, seed=828, color=None,
                     head_cy=0.30, foot_y=0.86):
    """【旋绕风 spiral】复刻原厂旋绕风效，三组叠加：
    ① 左上 7~9 道扇形放射细线（浅灰半透明、由粗渐细、末端尖细消失）
    ② 头部 2 道同心微弧（白色、贴发际线上方）
    ③ 脚底 1 道向上缠绕的螺旋（浅金、渐细）+ 飘叶。"""
    target = base_img if base_img is not None else getattr(draw, '_image', None)
    if target is None:
        return False
    rng = random.Random(seed)
    L = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    mw = min(W, H)

    # ① 扇形放射（左上汇聚 → 向右下铺开）
    cx, cy = 0.045 * W, 0.14 * H
    n = rng.randint(8, 9)
    for i in range(n):
        t = i / max(1, n - 1)
        ang = math.radians(8 + t * 62)          # 8°~70°
        ln = mw * rng.uniform(0.30, 0.52)
        wob = math.radians(rng.uniform(-6, 6))
        ex, ey = cx + math.cos(ang + wob) * ln, cy + math.sin(ang + wob) * ln
        mx, my = cx + math.cos(ang) * ln * 0.55, cy + math.sin(ang) * ln * 0.55 + mw * 0.012
        pts = _w_catmull([(cx, cy), (mx, my), (ex, ey)], 18)
        _w_taper(d, pts, max(2, int(mw * 0.0022)), 1, 120, 10, (208, 208, 208))

    # ② 头部同心微弧（白色）
    for k, rr in enumerate([0.155, 0.185]):
        rx, ry = mw * rr, mw * rr * 0.42
        bbox = [0.5 * W - rx, head_cy * H - ry, 0.5 * W + rx, head_cy * H + ry]
        d.arc(bbox, 196, 344, fill=(255, 255, 255, int(200 - k * 40)),
              width=max(2, int(mw * 0.0022)))

    # ③ 脚底螺旋（浅金，向上缠绕）
    sph = []
    for s in np.linspace(0, 1, 60):
        th = s * math.pi * 3.1 - math.pi * 0.15
        rad = mw * (0.115 - 0.075 * s)
        x = 0.50 * W + math.cos(th) * rad * 1.25
        y = foot_y * H - s * H * 0.26 + math.sin(th) * rad * 0.55
        sph.append((x, y))
    _w_taper(d, sph, max(2, int(mw * 0.0026)), 1, 190, 15, (240, 220, 170))

    # 飘叶
    if leaves_ok := True:
        for k, (lx, ly, sz) in enumerate([(0.20, 0.52, 0.028), (0.72, 0.58, 0.026),
                                          (0.30, 0.80, 0.030)]):
            _w_leaf(d, lx * W, ly * H, mw * sz, math.radians(120 + 40 * k),
                    (232, 196, 96, 235), (168, 128, 48, 245))
    target.paste(Image.alpha_composite(target.convert('RGBA'), L).convert('RGBA'), (0, 0))
    return True



def _detect_face_box(img):
    """用 OpenCV Haar 级联检测最大人脸，返回外扩后的像素框 (x0,y0,x1,y1)；失败返回 None。"""
    try:
        import cv2
        arr = np.array(img.convert('RGB'))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        xml = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        cc = cv2.CascadeClassifier(xml)
        h0, w0 = gray.shape
        faces = cc.detectMultiScale(gray, 1.1, 5,
                                    minSize=(int(w0 * 0.05), int(h0 * 0.05)))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        pad_x, pad_y = int(w * 0.40), int(h * 0.45)
        return (max(0, x - pad_x), max(0, y - pad_y),
                min(w0, x + w + pad_x), min(h0, y + h + pad_y))
    except Exception:
        return None


def _detect_faces_all(img, max_n=4):
    """检测多张人脸（合影用），返回外扩框列表。"""
    try:
        import cv2
        arr = np.array(img.convert('RGB'))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        h0, w0 = gray.shape
        faces = cc.detectMultiScale(gray, 1.1, 6,
                                    minSize=(int(w0 * 0.04), int(h0 * 0.04)))
        out = []
        for (x, y, w, h) in faces[:max_n]:
            px, py = int(w * 0.35), int(h * 0.4)
            out.append((max(0, x - px), max(0, y - py), min(w0, x + w + px), min(h0, y + h + py)))
        return out
    except Exception:
        return []


# ===== 丰富气泡形状（v2.9.6）：触发规则 + 自适应字号 + 越界夹取 =====
BUBBLE_POOL = {
    'people':   ['ellipse', 'rounded', 'shoujo', 'circle', 'petal', 'whisper', 'double', 'mini'],
    'nature':   ['ellipse', 'rounded', 'shoujo', 'wave', 'petal', 'caption', 'whisper'],
    'city':     ['ellipse', 'rounded', 'quad', 'whisper', 'shoujo', 'double'],
    'food':     ['ellipse', 'rounded', 'shoujo', 'petal', 'mini', 'caption'],
    'pet':      ['ellipse', 'rounded', 'circle', 'petal', 'mini', 'wave'],
    'sport':    ['ellipse', 'rounded', 'quad', 'mini', 'double', 'trumpet'],
    'unknown':  ['ellipse', 'rounded', 'shoujo', 'petal', 'wave', 'whisper', 'caption'],
}

# 拟声词触发规则：硬音效→爆炸框；轻柔音→线框/圆环；其他随机
HARD_SFX_KEYS = ('唰', '嘭', '咚', '轰', '啪', '砰', '咔', '铛', '哐', '嘶', '嗷', '哔', '咣')
SOFT_SFX_KEYS = ('簌簌', '沙沙', '哗啦', '淅沥', '咕嘟', '嗡嗡', '哒哒', '噼啪', '叮', '滴', '呼')


def pick_sfx_style(word):
    """按拟声词的"声音性格"选框型：硬→burst 爆炸框；柔→lines/ring；其他随机。"""
    if any(k in word for k in HARD_SFX_KEYS):
        return 'burst'
    if any(k in word for k in SOFT_SFX_KEYS):
        return random.choice(['lines', 'ring'])
    return random.choice(['burst', 'ring', 'plain'])


def pick_shape(text, scene, rng):
    """台词触发规则：按标点/语气选形状；无触发时按场景池随机。"""
    if ('！！' in text) or ('！' in text) or ('!' in text):
        return 'burst'          # 喊叫/强调 → 爆炸框
    if ('？' in text) or ('?' in text):
        return 'quad'           # 疑问 → 菱形框
    if ('……' in text) or ('...' in text):
        return 'whisper'        # 低语/迟疑 → 低语气框
    if ('心想' in text) or ('内心' in text):
        return 'thought'        # 内心独白 → 云朵框
    pool = BUBBLE_POOL.get(scene, BUBBLE_POOL['unknown'])
    return rng.choice(pool)


def _fix_orphan_line(lines, font, max_w):
    """v2.12.2：末行只剩 1 个字（如「~」「长」）时把它并回上一行，避免孤字行"""
    if len(lines) < 2:
        return lines
    if len(lines[-1]) == 1 and len(lines[-2]) >= 2:
        merged = lines[-2] + lines[-1]
        if font.getlength(merged) <= max_w * 1.25:
            return lines[:-2] + [merged]
    return lines


def draw_fancy_bubble(base_img, W, H, text, seed=0, scene='unknown',
                      tone='normal', corner='auto', max_w_frac=0.36, max_h_frac=0.30,
                      tail=None):
    """画「按台词触发形状 + 自适应字号 + 贴角不越界」的气泡，返回精确 bbox。"""
    rng = random.Random(seed)
    m = min(W, H)
    shape = pick_shape(text, scene, rng)
    if shape in ('circle', 'mini') and len(text) > 6:
        shape = rng.choice(['ellipse', 'rounded', 'petal', 'shoujo'])   # v2.12：小框只配短句

    # v2.12：形状面积系数——圆形/花瓣/星形/云形的外接框比文字块占地多，
    # 按系数收缩可用空间，避免"一个大圆圈盖住半张照片"（用户实测反馈）
    _AREA_K = {'circle': 1.18, 'petal': 1.20, 'burst': 1.16, 'thought': 1.22,
               'trumpet': 1.16, 'double': 1.10, 'mini': 1.06, 'wave': 1.05}
    _k = _AREA_K.get(shape, 1.0)
    hard_w = max_w_frac * W / _k
    max_h = max_h_frac * H / _k

    # 自适应字号：从大往小降，直到换行后能塞进 max_w × max_h
    fs = int(m * 0.050)
    fs_min = max(16, int(m * 0.028))
    _ratio = getattr(rt, 'TEXT_FIT', {}).get(shape, 0.80)
    _cap = min(hard_w, max_h)
    best = None
    # v2.12.2：判据必须用「最终渲染字号」排版（字先按 TEXT_FIT 缩小，再量行数），
    # 否则判据与实际排版两套字号 → 行数不一致，末行孤字拦不住。
    while fs >= fs_min:
        _tfs = max(int(m * 0.020), int(fs * _ratio))
        font = rt.load_font(FONT, _tfs)
        lines = wrap_chars(text, font, hard_w * 0.86)
        lh = font.getbbox('测')[3] + int(H * 0.006)
        need_w = max((font.getlength(l) for l in lines), default=0)
        need_h = len(lines) * lh
        if shape == 'circle':
            need = max((need_w + _tfs * 2.0) / 0.74, (need_h + _tfs * 1.25) / 0.74)
            fit_ok = need <= _cap
        else:
            fit_ok = need_w <= hard_w * 0.90 and need_h <= max_h
        if fit_ok:
            best = (font, lines, lh)
            if len(lines) == 1 or len(lines[-1]) >= 2:   # 末行只剩 1 字 → 继续缩字号
                break
        fs -= 2
    if best:
        font, lines, lh = best
    else:                                  # 极端情况：全部字号都不满足，用最小字号兜底
        _tfs = max(int(m * 0.020), int(fs_min * _ratio))
        font = rt.load_font(FONT, _tfs)
        lines = wrap_chars(text, font, hard_w * 0.86)
        lh = font.getbbox('测')[3] + int(H * 0.006)
    lines = _fix_orphan_line(lines, font, hard_w * 0.86)
    # v2.12.2：框与文字用【同一字号、同一换行宽度】——框按最终排版量，文字原样传入，
    # 保证「字不出框、框不出画布、文字不被裁」（旧版框按缩字号算、字按原字号排 → 字被挤出画面）
    _tfs = font.size
    _wrap = int(hard_w * 0.86)
    tfont = font
    tlines = lines
    ttw = max((font.getlength(l) for l in lines), default=_tfs)
    bw = ttw + _tfs * 2.0
    bh = len(lines) * lh + _tfs * 1.25
    if shape == 'circle':                      # v2.12：正圆按直径取方框，bbox 与视觉一致
        _d = max(bw, bh)
        bw = bh = max(min(_d, _cap), fs * 2.4)

    # 贴角 + 越界夹取（保证整个框都在画内）
    c = corner if corner in ('tl', 'tr', 'bl', 'br') else rng.choice(['tl', 'tr', 'bl', 'br'])
    mgn = int(0.035 * W)
    x0 = mgn if 'l' in c else W - mgn - bw
    y0 = mgn if c in ('tl', 'tr') else H - mgn - bh
    x0 = max(mgn, min(x0, W - bw - mgn))
    y0 = max(mgn, min(y0, H - bh - mgn))
    cx, cy = x0 + bw / 2, y0 + bh / 2

    border = max(3, int(m * rng.uniform(0.0045, 0.0065)))
    tail = tail if tail else rng.choice(TAIL_DIRS_8)
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    rt.draw_bubble(ld, shape, cx, cy, text, tfont, border, tail, tone, seed,
                   fit=False, wrap_w=_wrap)
    ang = rng.uniform(-2.2, 2.2)
    if abs(ang) > 0.1:
        layer = layer.rotate(ang, resample=Image.BICUBIC, center=(cx, cy))
    base_img.alpha_composite(layer)
    draw_fancy_bubble.last = {'shape': shape, 'tail': tail, 'corner': c}
    return (int(x0), int(y0), int(x0 + bw), int(y0 + bh))



if __name__ == '__main__':
    main()
