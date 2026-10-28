# -*- coding: utf-8 -*-
"""科研智能体方向 · v3 双海报生成
竖版 2700x6000 (poster_科研智能体_易拉宝_v3.png) + 宽版 6000x2700 (poster_科研智能体_宽版_v3.png)
v3 新增: A) PRODUCT MATRIX 产品组合板块(底座+五形态树状图, 纯 PIL)
         B) 真实照片带(圆角矩形+图注), 竖版 2 张 / 宽版 3 张
"""
import math
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

DIR = r"C:/Users/22150/小蜂相关资料/科研基础组件/海报与图表素材"
ASSETS = r"C:/Users/22150/小蜂相关资料/vesti/信息共享区间/08_品牌与视觉/宣传物料_20260918/assets"
FIGB = r"C:/Users/22150/小蜂相关资料/CRC-AI开发/final_check/main_illustrate/figures/figB_l2_gallery_zenodo.14509802_V10S15_055_C.png"
OUT_V = f"{DIR}/poster_科研智能体_易拉宝_v3.png"
OUT_W = f"{DIR}/poster_科研智能体_宽版_v3.png"

PURPLE = "#7b4fa3"
PURPLE_D = "#5e3a82"
PURPLE_M = "#9b6bc4"
LILAC = "#e8ddf2"
INK = "#141414"
GRAY = "#6b6b6b"
MSYH = "C:/Windows/Fonts/msyh.ttc"
GEORGIA_I = "C:/Windows/Fonts/georgiai.ttf"

def F(size, path=MSYH):
    return ImageFont.truetype(path, size)

def make_helpers(d):
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
    return draw_tracked, tracked_w, draw_tracked_right

def pixel_band(d, x0, y0, y1, cols=3, sq=44, step=56):
    random.seed(42)
    rows_n = (y1 - y0) // step
    accents = {(r, c) for r in range(rows_n) for c in range(cols) if random.random() < 0.045}
    for r in range(rows_n):
        y = y0 + r * step
        fade = 1.0 - 0.55 * (r / max(rows_n, 1))
        for c in range(cols):
            x = x0 + c * step
            if (r, c) in accents:
                col = PURPLE if random.random() < 0.4 else PURPLE_M
            else:
                base = (232, 221, 242)
                col = tuple(int(b + (255 - b) * (1 - fade)) for b in base)
            d.rectangle([x, y, x + sq, y + sq], fill=col)

ORGANELLES = [(-0.52, -0.42, 0.10), (0.42, -0.30, 0.085), (0.48, 0.38, 0.11),
              (-0.55, 0.45, 0.075), (0.05, -0.62, 0.07), (-0.10, 0.62, 0.09)]

def halftone_cell(d, CX, CY, R, SP):
    rng = np.random.default_rng(7)
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
            for ox, oy, orad in ORGANELLES:
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

def figb_crop(width):
    im = Image.open(FIGB).convert("RGB").crop((0, 0, 1440, 1480))
    h = round(im.height * width / im.width)
    return im.resize((width, h), Image.LANCZOS)

def paste_photo(img, path, x, y, w, h, radius=16):
    """圆角矩形居中裁剪贴图"""
    ph = ImageOps.fit(Image.open(path).convert("RGB"), (w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img.paste(ph, (x, y), mask)

WORKS = [
    ("01", "SGDB SCeQTL Portal", "SINGLE-CELL EQTL DISCOVERY PORTAL",
     "797 项后端 + 45 项前端测试全过 · Lighthouse 96–100"),
    ("02", "OncoTME AI 肿瘤微环境智能解析平台", "H&E → TME ECOTYPE",
     "常规 H&E 切片 AI 预测 TME 生态型 · macro-AUROC≈0.80 · 指导肿瘤免疫治疗"),
    ("03", "结直肠癌空间组学生态型预测系统", "CRC SPATIAL ECOTYPE",
     "873 片病理切片 Nature 风格热图全量交付 · TCGA + GSE 数据集"),
    ("04", "泛癌空间单细胞时空组学代谢基础模型", "PAN-CANCER METABOLIC FOUNDATION MODEL",
     "省级自然科学项目 · 核心成员"),
    ("05", "MPCG-Codon 密码子优化模型", "CODON OPTIMIZATION · OPEN SOURCE",
     "多模态物理约束 · GitHub 开源 500+ stars"),
    ("06", "VESTI Local-First AI 记忆底座", "LOCAL-FIRST MEMORY SUBSTRATE",
     "Recall@5 = 1.000 (内部评测) · 63 天 463 次提交从零到上线"),
    ("07", "nosad-agent 抑郁陪伴智能体", "MENTAL-HEALTH COMPANION AGENT",
     "语音情绪识别方向 · MVP"),
]
# 产品五形态: (序号, 标题行 list, 小字行 list)
FORMS = [
    ("①", ["Chrome 扩展"], ["已上架 Chrome Web Store"]),
    ("②", ["VESTI-SKILLS", "开源技能包"], ["vesti-memory /", "vesti-handoff · 404 stars"]),
    ("③", ["CLI 开发工具"], ["COMMAND-LINE", "TOOLING"]),
    ("④", ["MCP 检索服务"], ["MODEL CONTEXT", "PROTOCOL"]),
    ("⑤", ["桌面 App"], ["DESKTOP", "APPLICATION"]),
]
CASES = [
    ("某头部央企文化剧院", "合规知识库与制度智能体", "8,148 条条款入库"),
    ("某轮胎制造企业", "工业 OCR 标准解析", "48 项参数逐项可追溯"),
    ("某文旅品牌", "社媒创作智能体", "知识库质量分 94.4"),
    ("某省级行业协会", "政务门户网站建设", "54 项验收 0 失败"),
    ("千问 (Qwen) 官方合作", "热点推文流水线", "日更 3h→15min"),
]
BIG4 = [("8", "大场景智能体覆盖"), ("6", "个行业系统已交付"),
        ("873", "片病理切片交付"), ("8,148", "条结构化条款入库")]
EFF4 = [("60min→2min", "合规咨询响应"), ("3h→3min", "合同审查耗时"),
        ("−80%", "重复工作减少"), ("−70%", "招投标撰写流程压缩")]
AWARDS4 = ["◆ AI Hackathon Tour 全国总决赛金奖·赛道最佳",
           "◆ GOSIM Paris 2026 Audience Favorite",
           "◆ 南客松 S2 金奖·行业生产力第一 · 建邺区一等奖",
           "◆《人民日报》《南京发布》报道 · GitHub 500+ stars"]
TEAM = "核心团队: 南京大学 · 复旦大学 · 上海交通大学 · 中国科学技术大学 ｜ 紫金山英才计划 ｜ SIGIR"

# ============================================================
# 竖版 2700x6000
# ============================================================
def build_vertical():
    W, H = 2700, 6000
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    X0, XR = 360, 2380
    draw_tracked, tracked_w, draw_tracked_right = make_helpers(d)

    pixel_band(d, 90, 120, H - 240)

    # 品牌带
    logo = Image.open(f"{ASSETS}/logo.png").convert("RGBA").resize((150, 150), Image.LANCZOS)
    img.paste(logo, (X0, 140), logo)
    d.text((545, 152), "心迹群岛", font=F(64), fill=INK, stroke_width=1, stroke_fill=INK)
    draw_tracked(547, 240, "VESTI · NANJING", F(34), GRAY, tracking=8)
    draw_tracked_right(XR, 160, "科研智能体方向 · 报名材料", F(38), GRAY, tracking=4)
    draw_tracked_right(XR, 226, "NO. 2026 · HF · 001", F(38), PURPLE_M, tracking=10)

    # 标题区
    draw_tracked(X0, 370, "THIS IS VESTI · SCIENTIFIC RESEARCH AGENT", F(46), PURPLE, tracking=14)
    d.text((X0 - 8, 445), "科研智能体", font=F(270), fill=PURPLE, stroke_width=5, stroke_fill=PURPLE)
    draw_tracked(X0, 860, "SCIENTIFIC RESEARCH AGENT", F(56), PURPLE_M, tracking=17, stroke=1)
    d.text((X0, 955), "让 AI 读懂细胞, 也读懂思考", font=F(80), fill=INK, stroke_width=1, stroke_fill=INK)

    # 大数字带
    sy = 1085
    d.rectangle([X0, sy, XR, sy + 160], fill="#f4eef9")
    cw = (XR - X0) // 4
    for i, (num, lab) in enumerate(BIG4):
        cx0 = X0 + i * cw
        if i:
            d.line([cx0, sy + 30, cx0, sy + 130], fill="#d9c8ea", width=2)
        w = d.textlength(num, font=F(58))
        d.text((cx0 + (cw - w) / 2, sy + 20), num, font=F(58), fill=PURPLE,
               stroke_width=2, stroke_fill=PURPLE)
        w2 = d.textlength(lab, font=F(34))
        d.text((cx0 + (cw - w2) / 2, sy + 100), lab, font=F(34), fill=GRAY)
    # 效能行
    ey = 1285
    for i, (num, lab) in enumerate(EFF4):
        cx0 = X0 + i * cw
        w = d.textlength(num, font=F(46))
        d.text((cx0 + (cw - w) / 2, ey), num, font=F(46), fill=INK,
               stroke_width=1, stroke_fill=INK)
        w2 = d.textlength(lab, font=F(30))
        d.text((cx0 + (cw - w2) / 2, ey + 64), lab, font=F(30), fill=GRAY)
    d.line([X0, 1415, XR, 1415], fill="#d9c8ea", width=3)

    # 双视觉
    halftone_cell(d, 780, 1760, 330, 20)
    d.text((X0, 2205), "single-cell, read by AI", font=F(38, GEORGIA_I), fill=GRAY)
    fig = figb_crop(700)
    img.paste(fig, (1520, 1450))
    d.rectangle([1520, 1450, 1520 + fig.width, 1450 + fig.height], outline="#d9c8ea", width=2)
    d.text((1520, 1450 + fig.height + 12), "真实系统产出 · CRC 空间组学生态型热图 (AI 预测 vs 实际)",
           font=F(28), fill=GRAY)

    # 成果 7 行
    draw_tracked(X0, 2260, "SELECTED WORK · 科研与医学成果", F(46), PURPLE, tracking=10)
    d.line([X0, 2325, XR, 2325], fill="#d9c8ea", width=3)
    by = 2370
    for num, title, en, metric in WORKS:
        d.text((X0, by), num, font=F(50), fill=PURPLE_M, stroke_width=1, stroke_fill=PURPLE_M)
        tx = X0 + 160
        d.text((tx, by - 2), title, font=F(52), fill=INK, stroke_width=1, stroke_fill=INK)
        tw = d.textlength(title, font=F(52))
        draw_tracked(tx + tw + 28, by + 16, en, F(27), GRAY, tracking=4)
        d.text((tx, by + 82), metric, font=F(40), fill=PURPLE, stroke_width=1, stroke_fill=PURPLE)
        by += 148
        if num != "07":
            d.line([X0, by - 12, XR, by - 12], fill="#f0e8f7", width=2)
    # rows end 3406

    # PRODUCT MATRIX 产品组合
    draw_tracked(X0, 3450, "PRODUCT MATRIX · 产品组合: 一个底座, 五种形态", F(46), PURPLE, tracking=8)
    d.line([X0, 3515, XR, 3515], fill="#d9c8ea", width=3)
    card_y, card_h, card_w, gap = 3545, 265, 380, 25
    centers = []
    for i, (mark, titles, subs) in enumerate(FORMS):
        cx0 = X0 + i * (card_w + gap)
        centers.append(cx0 + card_w // 2)
        d.rounded_rectangle([cx0, card_y, cx0 + card_w, card_y + card_h],
                            radius=18, outline=PURPLE_M, width=3, fill="white")
        d.text((cx0 + 22, card_y + 16), mark, font=F(34), fill=PURPLE_M)
        ty = card_y + 66
        for t in titles:
            d.text((cx0 + 22, ty), t, font=F(34), fill=INK, stroke_width=1, stroke_fill=INK)
            ty += 46
        ty += 8
        for s in subs:
            d.text((cx0 + 22, ty), s, font=F(23), fill=GRAY)
            ty += 34
    # 树状连接线
    bus_y = 3832
    for cx in centers:
        d.line([cx, card_y + card_h, cx, bus_y], fill=PURPLE_M, width=3)
    d.line([centers[0], bus_y, centers[-1], bus_y], fill=PURPLE_M, width=3)
    d.line([centers[2], bus_y, centers[2], 3855], fill=PURPLE_M, width=3)
    # 底座块
    d.rounded_rectangle([520, 3855, XR, 3985], radius=16, fill=PURPLE)
    d.text((560, 3872), "VESTI Local-First AI 记忆底座", font=F(40), fill="white",
           stroke_width=1, stroke_fill="white")
    d.text((560, 3932), "跨平台捕获引擎 (界面变更存活率 100%) · 存储检索 Recall@5 = 1.000 (内部评测) · 五维认知提炼流水线",
           font=F(28), fill=LILAC)

    # 服务场景
    draw_tracked(X0, 4030, "WHAT WE SERVE · 服务场景", F(46), PURPLE, tracking=10)
    d.line([X0, 4095, XR, 4095], fill="#d9c8ea", width=3)
    d.text((X0, 4120), "我们打造并服务多类智能体: 医学 · 科研 · 合规 · 工业 · 社媒创作 · 政务 · 教育 · 心理健康 等",
           font=F(42), fill=INK)
    d.text((X0, 4180), "合作与服务机构覆盖高校与三甲医院: 南京大学 · 中国科学技术大学 · 南京鼓楼医院 · 哈尔滨第一医院 等",
           font=F(38), fill=GRAY)

    # 性能面板
    draw_tracked(X0, 4265, "MEMORY & LONG-CONTEXT METRICS · 记忆与长上下文指标", F(46), PURPLE, tracking=8)
    d.line([X0, 4330, XR, 4330], fill="#d9c8ea", width=3)
    panel = Image.open(f"{DIR}/panel_性能指标.png").convert("RGB")
    img.paste(panel, (X0, 4350))  # 2020x680 -> ends 5030

    # 真实案例
    draw_tracked(X0, 5070, "REAL CASES · 真实案例", F(46), PURPLE, tracking=10)
    d.line([X0, 5130, XR, 5130], fill="#d9c8ea", width=3)
    draw_tracked(X0, 5152, "客户(脱敏)", F(32), GRAY, tracking=4)
    draw_tracked(1060, 5152, "交付物", F(32), GRAY, tracking=4)
    draw_tracked_right(XR, 5152, "量化结果", F(32), GRAY, tracking=4)
    ry = 5198
    for name, deliv, num in CASES:
        d.text((X0, ry), name, font=F(42), fill=INK, stroke_width=1, stroke_fill=INK)
        d.text((1060, ry), deliv, font=F(42), fill=INK)
        w = d.textlength(num, font=F(44))
        d.text((XR - w, ry - 2), num, font=F(44), fill=PURPLE, stroke_width=1, stroke_fill=PURPLE)
        ry += 52
        d.line([X0, ry - 6, XR, ry - 6], fill="#f0e8f7", width=2)
    # table ends 5458

    # 奖项 + 照片带
    ay = 5490
    for k, line in enumerate(AWARDS4):
        d.text((X0, ay + k * 48), line, font=F(30), fill=INK)
    d.text((X0, ay + 4 * 48 + 8), TEAM, font=F(26), fill=GRAY)
    paste_photo(img, f"{ASSETS}/photo_hackathon-award_43.jpg", 1680, ay, 330, 210)
    paste_photo(img, f"{ASSETS}/photo_team_43.jpg", 2030, ay, 330, 210)
    d.text((1680, ay + 220), "AI Hackathon 全国总决赛", font=F(23), fill=GRAY)
    d.text((1680, ay + 252), "金奖颁奖现场", font=F(23), fill=GRAY)
    d.text((2030, ay + 220), "团队合照", font=F(23), fill=GRAY)

    # 底部
    qr = Image.open(f"{ASSETS}/qr_vesti_world.png").convert("RGB").resize((170, 170), Image.LANCZOS)
    img.paste(qr, (2210, 5810))  # ends 5980
    d.text((X0, 5825), "vesti.world", font=F(64), fill=PURPLE, stroke_width=2, stroke_fill=PURPLE)
    d.text((X0, 5915), "github.com/firefly-hefeng ｜ 心迹群岛(南京)智能科技有限公司",
           font=F(32), fill=INK)

    img.save(OUT_V, dpi=(76, 76))
    print("vertical v3 done", img.size)

# ============================================================
# 宽版 6000x2700
# ============================================================
def build_wide():
    W, H = 6000, 2700
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    XL, XR = 330, 5750
    draw_tracked, tracked_w, draw_tracked_right = make_helpers(d)

    pixel_band(d, 70, 80, H - 160, cols=3, sq=44, step=56)
    halftone_cell(d, 4600, 540, 330, 20)

    # 品牌头
    logo = Image.open(f"{ASSETS}/logo.png").convert("RGBA").resize((130, 130), Image.LANCZOS)
    img.paste(logo, (XL, 90), logo)
    d.text((485, 100), "心迹群岛", font=F(54), fill=INK, stroke_width=1, stroke_fill=INK)
    draw_tracked(487, 172, "VESTI · NANJING", F(30), GRAY, tracking=7)
    draw_tracked_right(5450, 100, "科研智能体方向 · 报名材料", F(34), GRAY, tracking=4)
    draw_tracked_right(5450, 155, "NO. 2026 · HF · 001", F(34), PURPLE_M, tracking=8)
    qr = Image.open(f"{ASSETS}/qr_vesti_world.png").convert("RGB").resize((180, 180), Image.LANCZOS)
    img.paste(qr, (5560, 80))
    wq = tracked_w("官网 · vesti.world", F(24))
    draw_tracked(5560 + (180 - wq) / 2, 268, "官网 · vesti.world", F(24), GRAY)

    # 标题区
    draw_tracked(XL, 300, "THIS IS VESTI · SCIENTIFIC RESEARCH AGENT", F(40), PURPLE, tracking=12)
    d.text((XL - 6, 370), "科研智能体", font=F(215), fill=PURPLE, stroke_width=4, stroke_fill=PURPLE)
    draw_tracked(XL, 640, "SCIENTIFIC RESEARCH AGENT", F(52), PURPLE_M, tracking=15, stroke=1)
    d.text((XL, 730), "让 AI 读懂细胞, 也读懂思考", font=F(62), fill=INK, stroke_width=1, stroke_fill=INK)
    d.text((XL, 822), "vesti.world ｜ github.com/firefly-hefeng ｜ 心迹群岛(南京)智能科技有限公司",
           font=F(36), fill=GRAY)

    # 数字带 6 格
    sy = 910
    d.rectangle([XL, sy, XR, sy + 150], fill="#f4eef9")
    cells6 = [("8", "大场景智能体"), ("6", "个行业系统交付"), ("873", "片病理切片"),
              ("8,148", "条条款入库"), ("60min→2min", "合规咨询响应"), ("3h→3min", "合同审查耗时")]
    cw = (XR - XL) // 6
    for i, (num, lab) in enumerate(cells6):
        cx0 = XL + i * cw
        if i:
            d.line([cx0, sy + 30, cx0, sy + 120], fill="#d9c8ea", width=2)
        w = d.textlength(num, font=F(52))
        d.text((cx0 + (cw - w) / 2, sy + 20), num, font=F(52), fill=PURPLE,
               stroke_width=2, stroke_fill=PURPLE)
        w2 = d.textlength(lab, font=F(32))
        d.text((cx0 + (cw - w2) / 2, sy + 94), lab, font=F(32), fill=GRAY)

    # Row1 三栏
    ty = 1110
    c1x, c1r = XL, 1930
    draw_tracked(c1x, ty, "SELECTED WORK · 科研与医学成果", F(38), PURPLE, tracking=6)
    d.line([c1x, ty + 52, c1r, ty + 52], fill="#d9c8ea", width=3)
    by = ty + 80
    for num, title, en, metric in WORKS:
        d.text((c1x, by), num, font=F(40), fill=PURPLE_M, stroke_width=1, stroke_fill=PURPLE_M)
        d.text((c1x + 110, by - 2), title, font=F(44), fill=INK, stroke_width=1, stroke_fill=INK)
        d.text((c1x + 110, by + 56), metric, font=F(30), fill=PURPLE)
        by += 96
        if num != "07":
            d.line([c1x, by - 10, c1r, by - 10], fill="#f0e8f7", width=2)
    # rows end 1862

    c2x, c2r = 2010, 3810
    draw_tracked(c2x, ty, "WHAT WE SERVE · 服务场景", F(38), PURPLE, tracking=6)
    d.line([c2x, ty + 52, c2r, ty + 52], fill="#d9c8ea", width=3)
    d.text((c2x, ty + 80), "我们打造并服务多类智能体:", font=F(34), fill=INK)
    d.text((c2x, ty + 140), "医学 · 科研 · 合规 · 工业", font=F(40), fill=PURPLE,
           stroke_width=1, stroke_fill=PURPLE)
    d.text((c2x, ty + 200), "社媒创作 · 政务 · 教育 · 心理健康 等", font=F(40), fill=PURPLE,
           stroke_width=1, stroke_fill=PURPLE)
    d.text((c2x, ty + 268), "合作与服务机构覆盖高校与三甲医院:", font=F(30), fill=GRAY)
    d.text((c2x, ty + 314), "南京大学 · 中国科学技术大学", font=F(30), fill=GRAY)
    d.text((c2x, ty + 356), "南京鼓楼医院 · 哈尔滨第一医院 等", font=F(30), fill=GRAY)
    ay = ty + 430
    draw_tracked(c2x, ay, "AWARDS · 奖项与认可", F(38), PURPLE, tracking=6)
    d.line([c2x, ay + 52, c2r, ay + 52], fill="#d9c8ea", width=3)
    for k, line in enumerate(AWARDS4):
        d.text((c2x, ay + 78 + k * 50), line, font=F(30), fill=INK)
    d.text((c2x, ay + 78 + 4 * 50 + 4), "核心团队: 南京大学 · 复旦大学 · 上海交通大学 · 中国科学技术大学",
           font=F(26), fill=GRAY)
    d.text((c2x, ay + 78 + 4 * 50 + 44), "紫金山英才计划 · SIGIR", font=F(26), fill=GRAY)
    # col2 ends ~ty+760 = 1870

    # Col3 真实产出图
    fig = figb_crop(760)
    fx = 4360
    img.paste(fig, (fx, ty))
    d.rectangle([fx, ty, fx + fig.width, ty + fig.height], outline="#d9c8ea", width=2)
    d.text((fx, ty + fig.height + 12), "真实系统产出 · CRC 空间组学生态型热图 (AI 预测 vs 实际)",
           font=F(28), fill=GRAY)

    # Row2: 照片带 + 产品矩阵
    py = 1965
    paste_photo(img, f"{ASSETS}/photo_hackathon-award_43.jpg", XL, py, 560, 200)
    paste_photo(img, f"{ASSETS}/photo_gosim-booth_43.jpg", XL + 600, py, 560, 200)
    paste_photo(img, f"{ASSETS}/photo_team_43.jpg", XL + 1200, py, 560, 200)
    d.text((XL, py + 210), "AI Hackathon 全国总决赛金奖颁奖现场", font=F(24), fill=GRAY)
    d.text((XL + 600, py + 210), "GOSIM Paris 2026 展台", font=F(24), fill=GRAY)
    d.text((XL + 1200, py + 210), "团队合照", font=F(24), fill=GRAY)

    # 产品矩阵: 左底座 + 右 5 卡
    mx0, mx1 = 2170, XR
    base_x1 = 2900
    mid_y = py + 100
    d.line([base_x1, mid_y, mx1, mid_y], fill=PURPLE_M, width=3)  # 横向总线(卡片压线)
    d.rounded_rectangle([mx0, py, base_x1, py + 200], radius=16, fill=PURPLE)
    d.text((mx0 + 30, py + 22), "VESTI Local-First", font=F(38), fill="white",
           stroke_width=1, stroke_fill="white")
    d.text((mx0 + 30, py + 76), "AI 记忆底座", font=F(38), fill="white",
           stroke_width=1, stroke_fill="white")
    d.text((mx0 + 30, py + 132), "捕获存活率 100% · Recall@5=1.000", font=F(23), fill=LILAC)
    d.text((mx0 + 30, py + 166), "五维认知提炼流水线", font=F(23), fill=LILAC)
    cw2 = 540
    for i, (mark, titles, subs) in enumerate(FORMS):
        cx0 = 2960 + i * (cw2 + 20)
        d.rounded_rectangle([cx0, py, cx0 + cw2, py + 200], radius=16,
                            outline=PURPLE_M, width=3, fill="white")
        d.text((cx0 + 18, py + 12), mark, font=F(30), fill=PURPLE_M)
        tyy = py + 54
        for t in titles:
            d.text((cx0 + 18, tyy), t, font=F(31), fill=INK, stroke_width=1, stroke_fill=INK)
            tyy += 40
        tyy += 6
        for s in subs:
            d.text((cx0 + 18, tyy), s, font=F(22), fill=GRAY)
            tyy += 32

    # 底部: 性能面板 + 案例表
    fy = 2225
    draw_tracked(XL, fy, "MEMORY & LONG-CONTEXT METRICS · 记忆与长上下文指标", F(32), PURPLE, tracking=6)
    panel = Image.open(f"{DIR}/panel_性能指标_wide.png").convert("RGB")
    img.paste(panel, (XL, fy + 40))  # 2900x430 -> ends 2695

    c3x = 3360
    draw_tracked(c3x, fy, "REAL CASES · 真实案例 (客户均脱敏)", F(38), PURPLE, tracking=6)
    d.line([c3x, fy + 52, XR, fy + 52], fill="#d9c8ea", width=3)
    ry = fy + 78
    for name, deliv, num in CASES:
        d.text((c3x, ry), name, font=F(34), fill=INK, stroke_width=1, stroke_fill=INK)
        d.text((c3x + 760, ry), deliv, font=F(32), fill=INK)
        w = d.textlength(num, font=F(34))
        d.text((XR - w, ry), num, font=F(34), fill=PURPLE, stroke_width=1, stroke_fill=PURPLE)
        ry += 54
        d.line([c3x, ry - 8, XR, ry - 8], fill="#f0e8f7", width=2)
    d.text((c3x, ry + 14), "−80% 重复工作 · −70% 招投标撰写流程压缩 · 1–2 周见原型 · 驻场交付 4–20 周",
           font=F(28), fill=GRAY)

    # 右下角像素簇
    cs, cstep = 40, 52
    bx, byy = 5600, 2550
    for (cc, rr) in [(0, 2), (1, 2), (2, 2), (2, 1), (2, 0)]:
        col = PURPLE if rr == 2 and cc < 2 else PURPLE_M
        d.rectangle([bx + cc * cstep, byy + rr * cstep,
                     bx + cc * cstep + cs, byy + rr * cstep + cs], fill=col)

    img.save(OUT_W, dpi=(76, 76))
    print("wide v3 done", img.size)

build_vertical()
build_wide()
