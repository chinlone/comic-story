#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""漫画动效决策器 v2.0（配合 references/effect-library.md）
根据场景/情绪/动作/人数 + 随机变量（发型、美化），输出：
该用哪些动效、可直接粘贴的 image_gen prompt、是否需要禁线区回贴、comic_story.py 建议参数。

用法:
  python3 decide_effects.py --list
  python3 decide_effects.py --scene zen
  python3 decide_effects.py --scene action --subjects 2
  python3 decide_effects.py --scene still --hair long --beautify strong
  python3 decide_effects.py --scene emotion --emotion angry
"""
import argparse
import json

SCENES = {
    'zen': dict(desc='禅意/冥想/静坐', main='A3', aux=['D1b', 'D2', 'D5', 'A5-weak'],
                ban=['A5', 'A7', 'B3'], mask=False),
    'still': dict(desc='静立/站姿演讲', main='A1', aux=['D1a'], ban=['A5'], mask=False),
    'action': dict(desc='动作/爆发/命中', main='A5', aux=['A7', 'C1', 'A12'],
                   ban=['A2', 'A3'], mask=True),
    'sport': dict(desc='奔跑/跳跃/运动', main='A7', aux=['A5', 'B3', 'A11'],
                  ban=['A2', 'A3'], mask=True),
    'autumn': dict(desc='秋日/户外/自然', main='A4', aux=['B1', 'D2', 'D7'], ban=['A5'], mask=False),
    'spring': dict(desc='春日/唯美/女性向', main='A4', aux=['B2', 'D4', 'D1a'], ban=['A5', 'A7'], mask=False),
    'rain': dict(desc='雨天/忧郁/出行', main='B9', aux=['B11', 'D9', 'D6'], ban=['A5'], mask=False),
    'snow': dict(desc='雪天/浪漫', main='B10', aux=['D1b', 'D6'], ban=['A5'], mask=False),
    'night': dict(desc='夜景/城市/车流', main='D8', aux=['A7', 'D5'], ban=['B1', 'B2'], mask=False),
    'sea': dict(desc='海边/湖边', main='B8', aux=['B11', 'D7', 'D9'], ban=['A5'], mask=False),
    'car': dict(desc='车内/机舱/地铁', main='A7', aux=['D6'], ban=['A2', 'A3'], mask=False),
    'food': dict(desc='美食/饮品', main='B5', aux=['D1a', 'D2'], ban=['A5', 'A7'], mask=False),
    'study': dict(desc='学习/图书馆/办公', main='A11', aux=['C1', 'D7'], ban=['A5'], mask=False),
    'pet': dict(desc='宠物', main='B6', aux=['E5', 'D2'], ban=['A5', 'A7'], mask=False),
    'business': dict(desc='商务/正装肖像', main='A3-light', aux=['D2'],
                     ban=['A5', 'A7', 'B1', 'B2'], mask=False),
    'group': dict(desc='双人/合影', main='none', aux=['C2'], ban=['A5'], mask=False),
    'emotion': dict(desc='情绪特写（汗/泪/怒/惊/羞）', main='E-symbol', aux=['A5', 'D4'],
                    ban=['B1', 'B9'], mask=False),
}

EMOTION = {
    'nervous': ['E1'], 'sad': ['E2'], 'angry': ['E3'], 'surprised': ['E4'],
    'love': ['E5'], 'dizzy': ['E6'], 'speechless': ['E7'], 'shock': ['E8'],
}

PROMPTS = {
    'A1': '加上【手绘日漫风格的白色气流风线】：3 条平行的柔白色 S 形弧线，从人物左侧肩部外开始，向下绕经腰部外侧、再绕到下方，末端变细自然消失；另在人物右肩后方加 1 条很短的白色小弧线。线条细 2-3 像素、半透明白、有手绘笔触的轻重变化。风线共 4 条，不要更多。',
    'A2': '加上【手绘日漫风格的白色环绕气流】：上下两层水平螺旋环绕——第一层围绕人物上半身（胸肩位置）呈水平螺旋绕一圈，第二层围绕腰部至下方再绕一圈；柔白色细线、半透明、手绘笔触浓淡变化、起笔略粗收笔渐细消失，线条 2-3 像素。',
    'A3': '加上【手绘日漫风格的白色环绕气流】：两道柔白色弧线立体环绕——第一道从人物左肩外侧绕到身后、从右腰外侧转出来；第二道从右腰绕到身后、从左腰前方转出来，形成"从身前绕到身后"的立体感；线条细而柔 2-3 像素、半透明白、起笔略粗收笔渐细、有手绘笔触。',
    'A3-light': '加上【很克制的白色轻环绕气流】：一道柔白色弧线从人物左肩外侧轻轻绕到身后、在右腰外侧转出；线条极细 2 像素、半透明白、起笔略粗收笔渐细消失、手绘笔触，整体轻盈克制不抢主体。',
    'A4': '加上【轻柔的白色微风线】：3 道轻细的柔白色弧线从画面左下向右上掠过，线条纤细轻微、半透明、手绘笔触，末端自然淡出。',
    'A5': '加上【日漫风格的爆炸强调放射集中线】：以交手势/情绪爆发点为中心向画面四周放射的锐利直线，根部粗、越远越细，白线与黑线交错；线条之间留清晰空白间隙、疏密相间，绝不糊成一片、不让中心过曝；放射线从人物外轮廓之外起笔，头部与脸部周围留出干净空白，不得切过脸。',
    'A5-weak': '背景里加极淡的放射光线：从人物背后向四周微弱发散，几乎融入背后的光晕，不要形成清晰线条。',
    'A6': '加上【边缘集中线】：从画面四周指向中心的密集直线，中心区域留出干净空白，形成聚焦与压迫感。',
    'A7': '加上【速度线】：数道平行的锐利速度线沿运动方向横贯画面，根部粗末端细，有墨线感。',
    'A10': '加上【锯齿声波线】：人物肩后或声源旁几道折线/闪电状的竖向声波线，表示声音传播或电流。',
    'A11': '加上【地面透视引导线】：从画面底部向主体汇聚的几道放射斜线，覆盖地面，增强空间纵深。',
    'A12': '加上【冲击波环】：以撞击/落地处为中心的几圈同心椭圆冲击波环，中空、边缘锐利。',
    'B1': '再画上【金黄银杏落叶】：大量金黄银杏叶空中飞舞、地面堆积，叶子有叶脉细节、金黄到橙黄渐变。',
    'B2': '再画上【飘落花瓣】：几片粉色花瓣随风飘落，柔和半透明，少量点缀。',
    'B3': '再画上【漫画式汗滴】：额角一颗白色水滴状汗滴，带黑色描边。',
    'B5': '再画上【热气丝】：从食物上方升起几缕半透明的白色热气丝线，轻盈升腾。',
    'B6': '再画上【毛发/衣摆飞扬】：宠物毛发被风轻轻吹起蓬松有空气感（人物则衣摆/发尾轻扬）。',
    'B7': '再画上【火焰与火星】：橙红火焰带黄色焰心呈飘动形态，周围细小橙红短线条模拟火星飞溅。',
    'B8': '再画上【水波纹/涟漪】：以主体为中心的同心圆弧水波纹，黑色细线向外扩散。',
    'B9': '再画上【雨丝】：斜向的细长雨丝覆盖画面，密度适中、半透明的细线，线条方向一致。',
    'B10': '再画上【飘雪】：细碎雪花飘落，近大远小，轻柔半透明。',
    'B11': '再画上【水花飞溅】：脚边溅起的水花，白色不透明水珠与短弧水线。',
    'D1': '并加上【人物轮廓背光】：沿人物头肩轮廓的柔和暖色光边，边缘柔化，人物像从光中浮现。',
    'D1a': '并加上【人物轮廓背光】：沿人物头肩外轮廓的柔和暖色光边，边缘柔化，人物像从光中浮现。',
    'D1b': '并加上【人物背后弥漫背光】：人物头部与肩背后方一大片暖白色（淡黄白）弥漫性柔光晕，从头顶向四周扩散照亮暗背景，形成圣光感，边缘柔和自然。',
    'D2': '再加 10-15 颗很小的暖白色十字星/圆点光尘，散在气流轨迹与人物周围，很淡。',
    'D4': '并在双颊加淡粉色腮红晕染，边缘柔和。',
    'D5': '并加上【暗角聚光】：画面四角与边缘明显压暗，中心人物区域明亮，形成聚光筒效果，聚焦主体。',
    'D6': '背景适度虚化（浅景深）：主体清晰、背景退后，边缘自然过渡。',
    'D7': '并加上【漏光/光束】：光束穿过缝隙形成斜射光带，空气中有细小光点在光带里闪烁。',
    'D8': '并加上【霓虹散景】：背景霓虹灯化作柔和虚化光斑（bokeh），主体边缘带冷暖交织的环境光。',
    'D9': '并加上【水面倒影】：地面或水面映出人物与光的倒影，波光粼粼。',
    'E1': '再画上【漫画式汗滴】：额角一颗白色水滴状汗滴，带黑色描边。',
    'E2': '再画上【漫画式泪滴】：眼角一两颗夸张的大泪滴（或泪流），白色带黑色描边。',
    'E3': '再画上【怒气符号】：额角爆出的十字形怒气符号（青筋），黑色粗线。',
    'E4': '再画上【惊叹/问号符号】：头顶漂浮一个巨大的惊叹号（或问号），白色填充带黑色描边。',
    'E5': '再画上【心形符号】：周围飘起几颗粉色心形符号，轻盈浮动。',
    'E6': '再画上【晕眩漩涡】：头顶一团大型螺旋漩涡线，表示头晕目眩。',
    'E7': '再画上【无语表现】：眼睛变成一片白色，或脸上垂下几条黑色竖线。',
    'E8': '再画上【炸毛/呆毛】：头顶一两根翘起的呆毛，或头发整体炸开。',
}

CLI = {
    'zen': '--ambient_style none --sfx none',
    'still': '--ambient_style none --sfx none',
    'action': '--ambient_style none --speedlines --speed_style burst --sfx "嘭"',
    'sport': '--ambient_style none --speedlines --speed_style burst --sfx "唰"',
    'autumn': '--ambient_style none --sfx "沙沙"',
    'spring': '--ambient_style none --sfx none',
    'rain': '--ambient_style none --sfx "淅沥"',
    'snow': '--ambient_style none --sfx none',
    'night': '--ambient_style none --sfx none',
    'sea': '--ambient_style none --sfx "哗啦"',
    'car': '--ambient_style none --sfx none',
    'food': '--ambient_style none --sfx "咕嘟"',
    'study': '--ambient_style none --sfx "哗啦"',
    'pet': '--ambient_style none --sfx "汪"',
    'business': '--ambient_style none --no_speedlines --sfx none',
    'group': '--mode double --ambient_style none --no_speedlines',
    'emotion': '--ambient_style none --sfx none',
}

HAIR = {
    'random': '发型可自然发挥（不必严格复刻原照片），保持符合人物气质的自然发型。',
    'keep': '发型必须与原照片完全一致：长度、刘海、分缝、蓬松度都不得改变。',
    'long': '头发比原照片更长一些、发尾自然飘逸（女性可被风轻轻吹起），保留原有分缝与刘海特征。',
    'fluffy': '头发比原照片更蓬松、有空气感，发丝呈自然放射状，露出额头（男性适用，不发丝飘动）。',
}
BEAUTIFY = {
    'light': '轻微美化：肤质干净、气色好，五官与轮廓保持原样。',
    'medium': '适度美化：肤白透亮、去细纹与瑕疵、五官清秀，仍是同一人。',
    'strong': '美化程度较高：眼睛略大、脸型更精致、皮肤透亮，但仍能一眼认出是同一人。',
}


def build(scene, subjects=1, hair='random', beautify='medium', emotion=None):
    s = SCENES[scene]
    if subjects >= 2 and scene not in ('group', 'action'):
        s = dict(s)
        s['aux'] = list(dict.fromkeys(s['aux'] + ['C2']))

    keys = []
    if s['main'] == 'E-symbol':
        emo = EMOTION.get(emotion or 'nervous', ['E1'])
        keys = emo + ['A5', 'D4']
    else:
        keys = [s['main']] + s['aux']
    parts = [PROMPTS[k] for k in keys if k in PROMPTS]

    prompt = (
        '在这个漫画画面上加上动效，其他所有内容（人物长相、服装、姿态、背景、文字标识）完全保持不变，'
        '不要改画风、不要改人物细节。\n\n'
        + ''.join(p + '\n' for p in parts)
        + '\n要求：除上面明确指定的元素外，不要再添加任何其他特效（未指定的放射线、速度线、花瓣、光斑等一律不要）；'
          '不要对话框、不要文字、不要拟声词（这两类由程序后期渲染）。所有线条与光点都不要压到人物脸部。'
    )
    prompt += '\n\n【人物处理】' + BEAUTIFY.get(beautify, BEAUTIFY['medium']) + HAIR.get(hair, HAIR['random'])

    return dict(scene=scene, desc=s['desc'], main=s['main'], aux=s['aux'], ban=s['ban'],
                effects_used=[k for k in keys if k in PROMPTS],
                need_mask_restore=s['mask'],
                hair_mode=hair, beautify=beautify, emotion=emotion,
                random_note='同一张照片建议按不同发型/美化各跑 3-4 次，让用户挑最喜欢的一版（每次只改一个变量）',
                image_gen_prompt=prompt,
                comic_story_args=CLI[scene],
                note=('需要 mask_restore.py 做头脸禁线区回贴（feather ≈ 矩形短边×5%）'
                      if s['mask'] else '无需禁线区回贴'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', choices=list(SCENES), help='场景类型')
    ap.add_argument('--subjects', type=int, default=1, help='主体人数（≥2 自动并入合影规则）')
    ap.add_argument('--hair', default='random', choices=list(HAIR), help='发型变量')
    ap.add_argument('--beautify', default='medium', choices=list(BEAUTIFY), help='美化强度')
    ap.add_argument('--emotion', default='nervous', choices=list(EMOTION),
                    help='emotion 场景的情绪类型')
    ap.add_argument('--list', action='store_true', help='列出全部场景')
    ap.add_argument('--image', default=None,
                    help='照片路径：自动粗判场景（启发式，置信度低时请改用 --scene 手动指定）')
    a = ap.parse_args()

    if a.image and not a.scene:
        try:
            import os as _os, sys as _sys
            _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
            from analyze_photo import analyze as _an
            _r = _an(a.image)
            a.scene = _r['scene'] if _r['scene'] in SCENES else 'still'
            import sys as _s2
            print('# auto-detect: scene=%s confidence=%d reasons=%s'
                  % (_r['scene'], _r['confidence'], _r['reasons']), file=_s2.stderr)
        except Exception as _e:
            a.scene = 'still'
            print('# auto-detect failed (%s), fallback scene=still' % _e)
    if a.list or not a.scene:
        for k, v in SCENES.items():
            print('%-9s %-18s 主效 %-9s 辅效 %-28s 禁用 %s'
                  % (k, v['desc'], v['main'], ','.join(v['aux']), ','.join(v['ban'])))
        return
    r = build(a.scene, a.subjects, a.hair, a.beautify, a.emotion)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
