#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""照片特征分析 → 推荐场景（配合 decide_effects.py 的 --image 使用）

输出客观特征 + 推荐场景 + 置信度。启发式规则，**置信度低时请人工确认**。
用法: python3 analyze_photo.py --image <照片>
"""
import argparse
import json
import numpy as np

def analyze(path):
    from PIL import Image
    im = Image.open(path).convert('RGB')
    W, H = im.size
    arr = np.array(im.resize((min(W, 480), int(min(W, 480) * H / W))), dtype=np.float32)
    h, w, _ = arr.shape
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    mx = arr.max(axis=2); mn = arr.min(axis=2)
    sat = np.where(mx > 1, (mx - mn) / np.maximum(mx, 1), 0)

    feats = dict(
        brightness=round(float(lum.mean()), 1),
        dark_ratio=round(float((lum < 60).mean()), 3),
        bright_ratio=round(float((lum > 200).mean()), 3),
        saturation=round(float(sat.mean()), 3),
        warmth=round(float(r.mean() - b.mean()), 1),
        green_ratio=round(float(((g > r + 12) & (g > b + 12)).mean()), 3),
        blue_ratio=round(float(((b > r + 12) & (b > g + 5)).mean()), 3),
        edge_density=round(float(np.abs(np.diff(lum, axis=1)).mean() / 12), 3),
    )
    # 上/下半蓝占比（判断水面/天空）
    half = h // 2
    blue_top = float(((b[:half] > r[:half] + 12) & (b[:half] > g[:half] + 5)).mean())
    blue_bot = float(((b[half:] > r[half:] + 12) & (b[half:] > g[half:] + 5)).mean())
    feats['blue_top'] = round(blue_top, 3)
    feats['blue_bottom'] = round(blue_bot, 3)

    # 人脸
    faces, face_frac = 0, 0.0
    try:
        import cv2
        gray = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        fs = cc.detectMultiScale(gray, 1.1, 5, minSize=(int(W * 0.05), int(H * 0.05)))
        faces = len(fs)
        if faces:
            area = sum(fw * fh for (_, _, fw, fh) in fs)
            face_frac = round(area / (W * H), 3)
    except Exception:
        pass
    feats['faces'] = faces
    feats['face_frac'] = face_frac

    # ---- 规则推场景（带置信度）----
    scene, conf, why = 'unknown', 1, []
    if face_frac > 0.10 and feats['dark_ratio'] > 0.25 and feats['brightness'] < 150:
        scene, conf, why = 'zen', 2, ['有主体人脸', '暗背景', '整体偏静（动作需人工确认）']
    elif face_frac > 0.06:
        scene, conf, why = 'still', 2, ['有主体人脸', '静态人像（动作幅度需人工确认）']
    elif feats['dark_ratio'] > 0.40 and feats['brightness'] < 95:
        scene, conf, why = 'night', 3, ['暗部占比高', '整体低亮度 → 夜景']
    elif feats['blue_bottom'] > 0.20 and feats['blue_top'] < feats['blue_bottom']:
        scene, conf, why = 'sea', 2, ['下半部蓝色多 → 水面']
    elif feats['green_ratio'] > 0.28 and feats['warmth'] > 12:
        scene, conf, why = 'autumn', 2, ['绿色多', '暖调 → 户外/秋色']
    elif feats['green_ratio'] > 0.28:
        scene, conf, why = 'spring', 1, ['绿色多 → 户外（春日/自然）']
    elif feats['brightness'] < 110 and feats['saturation'] < 0.22:
        scene, conf, why = 'rain', 1, ['低亮度', '低饱和 → 阴雨']
    elif feats['brightness'] > 190 and feats['saturation'] < 0.15:
        scene, conf, why = 'study', 1, ['高亮度', '低饱和 → 室内明亮空间']
    return dict(features=feats, scene=scene, confidence=conf,
                reasons=why,
                note='置信度 3=较可靠 / 2=需确认 / 1=建议人工判断场景')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    a = ap.parse_args()
    print(json.dumps(analyze(a.image), ensure_ascii=False, indent=2))
