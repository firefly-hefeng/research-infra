# -*- coding: utf-8 -*-
"""科研智能体方向 · 竖版易拉宝海报 2700x6000 (90cm x 200cm)
风格参照 roman-pixel-certificate.jpg; 文案口径取自 A4宣传页_v6_双面.html
"""
import math
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 2700, 6000
DIR = r"C:/Users/22150/小蜂相关资料/科研基础组件/海报与图表素材"
ASSETS = r"C:/Users/22150/小蜂相关资料/vesti/信息共享区间/08_品牌与视觉/宣传物料_20260918/assets"
OUT = f"{DIR}/poster_科研智能体_易拉宝.png"

PURPLE = "#7b4fa3"
PURPLE_D = "#5e3a82"
PURPLE_M = "#9b6bc4"
INK = "#141414"
GRAY = "#6b6b6b"

MSYH = "C:/Windows/Fonts/msyh.ttc"
GEORGIA_I = "C:/Windows/Fonts/georgiai.ttf"

def F(size, path=MSYH):
    return ImageFont.truetype(path, size)

img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
X0, XR = 360, 2380

def draw_tracked(x, y, text, font, fill, tracking=0, stroke=0):
    cx = x
    for ch in text:
        d.text((cx, y), ch, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
        cx += d.textlength(ch, font=font) + tracking
    return cx - tracking

def tracked_w(text, font, tracking=0):
    return sum(d.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)

def draw_tracked_right(xr, y, text, font, fill, tracking=0):
    return draw_tracked(xr - tracked_w(text, font, tracking), y, text, font, fill, tracking)

# ---------- 1. 左侧像素方块装饰带 ----------
random.seed(42)
sq, step = 44, 56
rows_n = (H - 240) // step
accents = {(r, c) for r in range(rows_n) for c in range(3) if random.random() < 0.045}
for r in range(rows_n):
    y = 120 + r * step
    fade = 1.0 - 0.55 * (r / rows_n)
    for c in range(3):
        x = 90 + c * step
        if (r, c) in accents:
            col = PURPLE if random.random() < 0.4 else PURPLE_M
        else:
            base = (232, 221, 242)
            col = tuple(int(b + (255 - b) * (1 - fade)) for b in base)
        d.rectangle([x, y, x + sq, y + sq], fill=col)

# ---------- 2. 顶部品牌带 ----------
logo = Image.open(f"{ASSETS}/logo.png").convert("RGBA").resize((170, 170), Image.LANCZOS)
img.paste(logo, (X0, 145), logo)
d.text((560, 160), "心迹群岛", font=F(66), fill=INK, stroke_width=1, stroke_fill=INK)
draw_tracked(562, 258, "VESTI · NANJING", F(36), GRAY, tracking=8)
draw_tracked_right(XR, 170, "科研智能体方向 · 报名材料", F(40), GRAY, tracking=4)
draw_tracked_right(XR, 240, "NO. 2026 · HF · 001", F(40), PURPLE_M, tracking=10)

# ---------- 3. 引言 + 超大标题 ----------
draw_tracked(X0, 400, "THIS IS VESTI · SCIENTIFIC RESEARCH AGENT", F(48), PURPLE, tracking=14)
d.text((X0 - 8, 490), "科研智能体", font=F(320), fill=PURPLE, stroke_width=5, stroke_fill=PURPLE)
draw_tracked(X0, 985, "SCIENTIFIC RESEARCH AGENT", F(66), PURPLE_M, tracking=18, stroke=1)
d.text((X0, 1120), "让 AI 读懂细胞, 也读懂思考", font=F(88), fill=INK, stroke_width=1, stroke_fill=INK)
d.line([X0, 1300, XR, 1300], fill="#d9c8ea", width=3)

# ---------- 4. 半调网点主视觉: 单细胞 ----------
CX, CY, R = 1370, 1900, 480
SP = 22
rng = np.random.default_rng(7)
organelles = [(-0.52, -0.42, 0.10), (0.42, -0.30, 0.085), (0.48, 0.38, 0.11),
              (-0.55, 0.45, 0.075), (0.05, -0.62, 0.07), (-0.10, 0.62, 0.09)]

def density(nx, ny):
    r = math.hypot(nx, ny)
    if r > 1.25:
        return 0.0
    val = 0.0
    if r <= 1.0:
        val += 0.10 * (1 - r)
        val += 0.95 * math.exp(-((r - 0.965) / 0.045) ** 2)
        dn = math.hypot(nx + 0.24, ny - 0.06)
        if dn < 0.44:
            val += 0.55 * (1 - dn / 0.44)
        val += 0.9 * math.exp(-((dn - 0.44) / 0.04) ** 2)
        dncl = math.hypot(nx + 0.32, ny - 0.14)
        if dncl < 0.13:
            val += 0.9 * (1 - dncl / 0.13)
        for ox, oy, orad in organelles:
            do = math.hypot(nx - ox, ny - oy)
            if do < orad:
                val += 0.75 * (1 - do / orad)
    else:
        val = 0.30 * math.exp(-((r - 1.0) / 0.10) ** 2)
    return min(1.0, val)

n = int(2 * R * 1.25 / SP) + 1
for i in range(n + 1):
    for j in range(n + 1):
        px = CX - 1.25 * R + i * SP
        py = CY - 1.25 * R + j * SP
        nx, ny = (px - CX) / R, (py - CY) / R
        den = density(nx, ny)
        if den <= 0.02:
            continue
        if math.hypot(nx, ny) > 1.0 and rng.random() > den * 2.2:
            continue
        rad = den * SP * 0.62 * (0.85 + 0.3 * rng.random())
        if rad < 1.0:
            continue
        d.ellipse([px - rad, py - rad, px + rad, py + rad],
                  fill=PURPLE_D if den > 0.62 else PURPLE)
d.text((X0, 2445), "single-cell, read by AI", font=F(42, GEORGIA_I), fill=GRAY)

# ---------- 5. 科研成果亮点 ----------
draw_tracked(X0, 2540, "SELECTED WORK · 科研成果", F(46), PURPLE, tracking=10)
d.line([X0, 2610, XR, 2610], fill="#d9c8ea", width=3)
blocks = [
    ("01", "SGDB SCeQTL Portal", "SINGLE-CELL EQTL DATA DISCOVERY PORTAL",
     "单细胞 eQTL 数据智能发现门户 · 科研智能体",
     "797 项后端测试全过 · 45 项前端测试全过 · Lighthouse 96–100"),
    ("02", "MPCG-Codon 密码子优化模型", "CODON OPTIMIZATION · OPEN SOURCE",
     "多模态物理约束的密码子优化开源模型",
     "GitHub 开源 · 主仓矩阵累计 500+ stars"),
    ("03", "泛癌空间单细胞时空组学代谢基础模型", "PAN-CANCER SPATIOTEMPORAL METABOLIC FOUNDATION MODEL",
     "面向泛癌代谢重编程的单细胞基础模型",
     "省级自然科学项目 · 核心成员"),
    ("04", "VESTI Local-First AI 记忆底座", "LOCAL-FIRST AI MEMORY SUBSTRATE",
     "本地优先的 AI 长期记忆存储与检索基础设施",
     "Recall@5 = 1.000 (内部评测) · 63 天 463 次提交从零到上线"),
]
by = 2670
BH = 280
for num, title, en, desc, metric in blocks:
    d.text((X0, by), num, font=F(62), fill=PURPLE_M, stroke_width=1, stroke_fill=PURPLE_M)
    tx = X0 + 180
    d.text((tx, by - 4), title, font=F(68), fill=INK, stroke_width=1, stroke_fill=INK)
    draw_tracked(tx, by + 94, en, F(32), GRAY, tracking=6)
    d.text((tx, by + 138), desc, font=F(44), fill=INK)
    d.text((tx, by + 196), metric, font=F(46), fill=PURPLE, stroke_width=1, stroke_fill=PURPLE)
    by += BH
    if num != "04":
        d.line([X0, by - 16, XR, by - 16], fill="#f0e8f7", width=2)
# blocks end: 2670 + 4*280 = 3790

# ---------- 6. 性能图表面板 ----------
draw_tracked(X0, 3830, "MEMORY & LONG-CONTEXT METRICS · 记忆与长上下文指标", F(46), PURPLE, tracking=8)
d.line([X0, 3900, XR, 3900], fill="#d9c8ea", width=3)
panel = Image.open(f"{DIR}/panel_性能指标.png").convert("RGB")
img.paste(panel, (X0, 3925))  # 2020x880 -> ends 4805

# ---------- 7. 商业交付量化指标条 ----------
sy = 4840
d.rectangle([X0, sy, XR, sy + 200], fill="#f4eef9")
cells = [("60min→2min", "合规咨询响应"), ("3h→3min", "合同审查耗时"),
         ("−80%", "重复工作减少"), ("−70%", "招投标撰写流程压缩")]
cw = (XR - X0) // 4
for i, (num, lab) in enumerate(cells):
    cx0 = X0 + i * cw
    if i:
        d.line([cx0, sy + 36, cx0, sy + 164], fill="#d9c8ea", width=2)
    w = d.textlength(num, font=F(62))
    d.text((cx0 + (cw - w) / 2, sy + 28), num, font=F(62), fill=PURPLE,
           stroke_width=2, stroke_fill=PURPLE)
    w2 = d.textlength(lab, font=F(38))
    d.text((cx0 + (cw - w2) / 2, sy + 122), lab, font=F(38), fill=GRAY)

# ---------- 8. 真实案例精简表 ----------
draw_tracked(X0, 5100, "REAL CASES · 真实案例", F(46), PURPLE, tracking=10)
d.line([X0, 5170, XR, 5170], fill="#d9c8ea", width=3)
draw_tracked(X0, 5196, "客户(脱敏)", F(32), GRAY, tracking=4)
draw_tracked(1060, 5196, "交付物", F(32), GRAY, tracking=4)
draw_tracked_right(XR, 5196, "量化结果", F(32), GRAY, tracking=4)
cases = [
    ("某头部央企文化剧院", "合规知识库与制度智能体", "8,148 条条款入库"),
    ("某轮胎制造企业", "工业 OCR 标准解析", "48 项参数逐项可追溯"),
    ("某文旅品牌", "社媒创作智能体", "知识库质量分 94.4"),
    ("某省级行业协会", "政务门户网站建设", "54 项验收 0 失败"),
    ("千问 (Qwen) 官方合作", "热点推文流水线", "日更 3h→15min"),
]
ry = 5250
for name, deliv, num in cases:
    d.text((X0, ry), name, font=F(42), fill=INK, stroke_width=1, stroke_fill=INK)
    d.text((1060, ry), deliv, font=F(42), fill=INK)
    w = d.textlength(num, font=F(44))
    d.text((XR - w, ry - 2), num, font=F(44), fill=PURPLE, stroke_width=1, stroke_fill=PURPLE)
    ry += 62
    d.line([X0, ry - 8, XR, ry - 8], fill="#f0e8f7", width=2)
# table ends: 5250 + 5*62 = 5560

# ---------- 9. 奖项带 ----------
ay = 5595
d.text((X0, ay), "◆ AI Hackathon Tour 全国总决赛金奖·赛道最佳  ◆ GOSIM Paris 2026 Audience Favorite",
       font=F(40), fill=INK)
d.text((X0, ay + 58), "◆ 南客松 S2 金奖·行业生产力第一  ◆ 建邺区青年创新创业大赛一等奖  ◆《人民日报》《南京发布》报道",
       font=F(40), fill=INK)
d.text((X0, ay + 116), "核心团队来自南京大学 · 复旦大学 · 上海交通大学 · 中国科学技术大学 ｜ 紫金山英才计划 ｜ SIGIR",
       font=F(34), fill=GRAY)
# awards end ~5760

# ---------- 10. 底部 ----------
qr = Image.open(f"{ASSETS}/qr_vesti_world.png").convert("RGB").resize((270, 270), Image.LANCZOS)
img.paste(qr, (2100, 5720))  # ends y=5990, x=2370; 避开奖项行 (ends y~5695)
d.text((X0, 5790), "vesti.world", font=F(84), fill=PURPLE, stroke_width=2, stroke_fill=PURPLE)
d.text((X0, 5910), "github.com/firefly-hefeng ｜ 心迹群岛(南京)智能科技有限公司",
       font=F(40), fill=INK)

img.save(OUT, dpi=(76, 76))
print("poster v3 done", img.size)
