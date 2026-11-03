#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""禁线区回贴（漫画故事技能配套）
把「模型画了放射线/风线的图」中指定的禁线区（头/脸/颈肩）擦回原底图，
既保留绘图模型的手绘线条质感，又 100% 保证人物面部干净不被切。

用法:
  python3 mask_restore.py --base <原底图> --model <模型输出图> --out <成品> \
      [--rect 0.34,0.04,0.66,0.46] [--feather 46]

--rect 为比例坐标 x0,y0,x1,y1（默认单人肖像头肩区）。
--feather 为边界羽化像素（默认 46，越大过渡越柔）。
"""
import argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, help='原底图（未加线的干净图）')
    ap.add_argument('--model', required=True, help='绘图模型输出（含放射线/风线）')
    ap.add_argument('--out', required=True, help='输出路径')
    ap.add_argument('--rect', default='0.34,0.04,0.66,0.46',
                    help='禁线区比例 x0,y0,x1,y1（默认单人肖像头肩）')
    ap.add_argument('--feather', type=int, default=46, help='边界羽化像素')
    a = ap.parse_args()

    x0, y0, x1, y1 = [float(v) for v in a.rect.split(',')]
    base = Image.open(a.base).convert('RGB')
    model = Image.open(a.model).convert('RGB')
    if model.size != base.size:
        model = model.resize(base.size, Image.LANCZOS)
    W, H = base.size

    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).rectangle(
        [int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(a.feather))

    out = Image.composite(base, model, mask)
    out.save(a.out)

    arr_b = np.array(base, dtype=np.int16)
    arr_o = np.array(out, dtype=np.int16)
    d = np.abs(arr_o - arr_b).mean(axis=2)
    cx0, cy0 = int((x0 + 0.04) * W), int((y0 + 0.04) * H)
    cx1, cy1 = int((x1 - 0.04) * W), int((y1 - 0.04) * H)
    core = 100 * (d[cy0:cy1, cx0:cx1] > 6).mean() if cx1 > cx0 and cy1 > cy0 else 0
    print('[mask_restore] saved %s | 核心禁线区改动 %.2f%% | 全图改动 %.2f%%'
          % (a.out, core, 100 * (d > 6).mean()))


if __name__ == '__main__':
    main()
