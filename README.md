<p align="center">
  <img src="assets/cover.jpg" alt="漫画故事封面" width="320">
</p>

<p align="center">
  <img src="assets/social-preview.png" alt="GitHub 社交预览图（链接分享缩略图）" width="480">
</p>

# 漫画故事（Comic Story）

**Turn one real photo into a Japanese-comic-style illustration with dialogue, SFX and emotion symbols — a single panel that already tells a story.**

把**一张真实照片**转成日系赛璐珞漫画风插画，并自动配上贴合场景的文字、拟声词与情绪符号——**单张就有故事感**。

> **关于示例图**：本仓库不含任何真人照片示例——真实人物肖像涉及授权与隐私，
> 公开分发不宜附带。想看效果请用自己的照片跑一遍（流程见 `SKILL.md` 六步工作流）。

不是给照片套滤镜，而是图生图"重绘"成漫画，再叠加漫画排版层：

- 人物长相 / 服装 / 背景 / 照片上原有文字 **逐字保真**
- 15 种漫画对话框 + 斜向尾巴，按场景与台词自动挑，不千篇一律
- 4 种拟声词音效（爆炸星 / 同心圈 / 放射线 / 纯描边）
- 10 种情绪符号（汗滴 / 泪 / 怒气 / 惊叹 / 问号 / 心形 / 闪光 / 腮红 / 黑化排线 / 网点）纯程序绘制，自动避脸
- 分层文案：主台词 + 内心独白 + 旁白

> 本技能只做**单格漫画图**，不做多格分镜与漫剧长图（那属于 `ai-manga-drama`）。

---

## 适用 / 不适用

| 用 | 不用 |
|---|---|
| 上传照片 + "转漫画 / 漫画故事 / 照片转漫画风格 / 做成漫画头像" | 只说"画一张漫画"（无照片 → 直接生图） |
| 想把合照、宠物、风景、美食做成有故事的漫画图 | 多格漫画、漫剧、动画 |
| 需要人物保真的漫画化 | 照片精修 / 美颜 / 滤镜 |

---

## 安装

1. 解压后得到 `漫画故事/` 目录，放进你的 skills 目录即可（保持目录名不变）。
2. 依赖：

```bash
pip install pillow numpy
# 可选：装了 cv2 才有自动人脸检测与人物剪影，没装会自动降级，不报错
pip install opencv-python
```

3. 自检：

```bash
python3 scripts/comic_story.py --help
```

---

## 快速开始

```bash
# 1) 单人照片：一句台词 + 自动情绪符号
python3 scripts/comic_story.py \
  --input photo_comic.png --output out.png \
  --mode single --t1 "今天也要甜一点~" \
  --scene people --fxc 47 --fyc 33 --seed 7

# 2) 双人/合照：两个对话框（右下台词 + 左下旁白）
python3 scripts/comic_story.py \
  --input group_comic.png --output out.png \
  --mode double --t1 "一起精进，一起变好~" --t2 "和同路的人一起向前" \
  --scene people --seed 3

# 3) 加拟声词（自动选框型）
python3 scripts/comic_story.py --input in.png --output out.png \
  --mode single --t1 "开拍啦~" --sfx "咔嚓" --scene people

# 4) 指定情绪符号（阳光派）
python3 scripts/comic_story.py --input in.png --output out.png \
  --mode single --t1 "好运来~" --emotion heart,sparkle,blush

# 5) 黑化风格（必须显式开启）
python3 scripts/comic_story.py --input in.png --output out.png \
  --mode single --t1 "心情有点沉~" --emotion dark,dots --dark
```

> `--input` 必须是**已经转成漫画风的底图**（技能工作流第 4 步用 image_gen 图生图产出），
> 本脚本负责在上面排版文字、音效与符号。完整 6 步工作流见 `SKILL.md`。

---

## 主要参数

| 参数 | 说明 |
|---|---|
| `--mode single/double` | 单人（一个框）或双人（右下台词 + 左下旁白） |
| `--t1 / --t2` | 台词文本；单框建议 ≤ 24 字，双人每框 ≤ 20 字 |
| `--sfx` | 拟声词：具体词 / `auto`（按场景词库随机，35% 概率不配）/ `none` |
| `--scene` | `people / nature / city / food / pet / sport / unknown`，决定形状池与音效词库 |
| `--emotion` | `auto`（按文案情绪，默认只出阳光派）/ `none` / `heart,sparkle` 等逗号分隔 |
| `--dark` | 允许黑化派符号（`dark` 排线 / `dots` 网点），**只在用户明确要求黑化时才加** |
| `--fxc / --fyc` | 人脸中心百分比（0–100），用于避脸；不传则尝试 cv2 自动检测 |
| `--no_speedlines` | 关闭放射速度线（合影、静态柔光场景建议关） |
| `--ambient_style none/swirl` | 程序氛围风线；默认 `none`（动效交给绘图模型画） |
| `--seed` | 随机种子；同 seed 结果可复现，换 seed 可对比挑版本 |

脚本结束会打印一行 `[report]` JSON，含 `shapes`（本次用的框型）、`symbols`（符号）、
`main_box`/`sfx_box`（框坐标），可用于自动自检。

---

## 目录结构

```
漫画故事/
├── SKILL.md                  技能定义与完整工作流（6 步）+ 变更日志
├── README.md                 本文件
├── scripts/
│   ├── comic_story.py        主渲染脚本（排版总装）
│   ├── render_text.py        对话框/文字底层库（15 种形状、缺字兜底）
│   ├── symbols.py            情绪符号库（10 种，纯程序绘制）
│   ├── decide_effects.py     动效决策器（17 类场景）
│   ├── analyze_photo.py      照片结构化分析辅助
│   └── mask_restore.py       禁线区回贴（保脸）
├── fonts/
│   ├── ZCOOLKuaiLe.ttf       圆润手写体（对话框/拟声词）
│   ├── fallback_cjk.ttf      缺字兜底子集（195KB）
│   └── zcool_missing.txt     588 个缺字符清单
└── references/
    ├── style-spec.md         画风规范 + 智能配色 + 配文模板
    ├── effect-library.md     54 个漫画动效符号库
    └── examples.md           人像/宠物/风景完整示例
```

---

## 常见问题

**Q：文字出现 □ 方块？**
主字体缺 `· ℃ ① → ★` 等 588 个符号，技能已内置 `fallback_cjk.ttf` 自动补字。
若仍出现方块，说明是连兜底字体也没有的生僻字，换一个说法即可。

**Q：对话框盖住人脸/照片主体？**
传 `--fxc/--fyc`（人脸中心百分比）让脚本避让；框面积已被限制在画面 4% 以内并只贴角。

**Q：文案太长，字变得很小？**
单框建议 ≤ 24 字。超长会自动缩字号硬塞，可读性下降——拆句或精简更好。

**Q：想要更「黑化/emo」的风格？**
加 `--emotion dark,dots --dark`，并只在你确实想要这种调性时使用。默认调性是阳光正能量。

**Q：能保证每张脸都不一样吗？**
不能，也不该——本技能是照片转漫画，**脸型五官必须稳定**才像本人。
变化落在装饰层：对话框形状、尾巴角度、音效、情绪符号、文案；**发型允许自然发挥**。

---

## 授权

- 代码：随技能分发，可自由修改使用。
- 字体：`ZCOOLKuaiLe.ttf` 与 `fallback_cjk.ttf`（Noto Sans SC 子集）均为
  **SIL Open Font License 1.1**，允许免费商用、嵌入与再分发，保留 OFL 声明即可。

---

## 版本

当前 **v2.12.3**（2026-11-02）。完整变更历史见 `SKILL.md` 顶部日志。

---

## 关于 GitHub / Claude Skills 兼容性

- 本仓库目录名用英文 `comic-story`，方便命令行与 URL；技能自身的 `SKILL.md` 里 `name` 仍为中文 `漫画故事`——这是 **ima.copilot / skillhub** 平台使用的名字。
- 若要在 **Anthropic Claude Skills** 生态里使用，`SKILL.md` 的 frontmatter `name` 需符合 `^[a-z0-9-]{1,64}$`，把 `name: 漫画故事` 改成 `name: comic-story` 即可，其余无需改动。
- 字体体积较大（2.7MB + 195KB），直接入库即可，未使用 Git LFS。

## 贡献

欢迎提 Issue / PR。改动前请先跑一遍自检：

```bash
python3 scripts/comic_story.py --input demo_comic.png --output /tmp/out.png \
  --mode single --t1 "测试一下~" --scene people --seed 7
```

脚本会打印 `[report]` JSON（`shapes` / `symbols` / `main_box` / `sfx_box`），可据此判断形状、符号与框位是否符合预期。
