# -*- coding: utf-8 -*-
"""科研智能体报名素材 · 图表 1/2
配色: #7b4fa3 / #9b6bc4 / #e8ddf2, 白底, 去 top/right spine, dpi=200
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for f in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"]:
    font_manager.fontManager.addfont(f)
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

OUT = r"C:/Users/22150/小蜂相关资料/科研基础组件/海报与图表素材"
PURPLE = "#7b4fa3"
PURPLE_L = "#b48fd0"
PURPLE_XL = "#e8ddf2"
INK = "#1a1a1a"
GRAY = "#666666"

# ---------------- 图 1: 核心系统质量指标 ----------------
# (标签, 数值, 是否实测, 显示文本)
rows = [
    ("VESTI 记忆底座 · Recall@5",        1.000, True,  "1.000"),
    ("针尖检索 · NIAH*",                 1.000, False, "1.00"),
    ("长上下文检索 · RULER*",            0.970, False, "0.97"),
    ("长期对话记忆 · LoCoMo*",           0.940, False, "0.94"),
    ("制度智枢 · 回归测试通过率",         0.931, True,  "93.1%"),
    ("制度智枢 · Recall@5",              0.926, True,  "0.926"),
    ("记忆一致性 · LongMemEval*",        0.920, False, "0.92"),
    ("制度智枢 · MRR",                   0.737, True,  "0.737"),
]
labels = [r[0] for r in rows][::-1]
vals = [r[1] for r in rows][::-1]
cols = [PURPLE if r[2] else PURPLE_L for r in rows][::-1]
txts = [r[3] for r in rows][::-1]

fig, ax = plt.subplots(figsize=(10, 6.4), dpi=200)
bars = ax.barh(labels, vals, color=cols, height=0.62, zorder=3)
for b, t in zip(bars, txts):
    ax.text(b.get_width() + 0.012, b.get_y() + b.get_height() / 2, t,
            va="center", ha="left", fontsize=11, color=INK, fontweight="bold")
ax.set_xlim(0, 1.12)
ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
ax.xaxis.grid(True, color=PURPLE_XL, linewidth=0.9, zorder=0)
ax.set_axisbelow(True)
for s in ["top", "right"]:
    ax.spines[s].set_visible(False)
for s in ["left", "bottom"]:
    ax.spines[s].set_color("#cccccc")
ax.tick_params(axis="y", labelsize=11.5, colors=INK, length=0)
ax.tick_params(axis="x", labelsize=9.5, colors=GRAY)
ax.set_title("科研智能体核心系统质量指标", fontsize=17, color=INK,
             loc="left", pad=26, fontweight="bold")
ax.text(0, 1.015, "Quality metrics of VESTI agent systems (internal evaluation)",
        transform=ax.transAxes, fontsize=9.5, color=GRAY)
fig.text(0.125, 0.015,
         "数据来源: VESTI 内部评测 / 项目交付记录, 2026-10。深紫 = 内部实测; 浅紫带 * = 参照对应公开评测协议的内部口径估计值。",
         fontsize=8.5, color=GRAY)
fig.tight_layout(rect=[0, 0.04, 1, 1])
fig.savefig(f"{OUT}/chart1_核心系统质量指标.png", facecolor="white")
plt.close(fig)

# ---------------- 图 2: 开源矩阵 GitHub Stars ----------------
repos = [("VESTI-SKILLS", 404, "404"),
         ("VESTI 主仓", 360, "360+"),
         ("SGDB_Agent", 19, "19"),
         ("knight", 17, "17"),
         ("MPCG", 3, "3")]
names = [r[0] for r in repos]
stars = [r[1] for r in repos]
disp = [r[2] for r in repos]
shades = ["#6b3f92", PURPLE, "#9b6bc4", "#b48fd0", "#cbb0de"]

fig, ax = plt.subplots(figsize=(10, 6.0), dpi=200)
bars = ax.bar(names, stars, color=shades, width=0.58, zorder=3)
for b, t in zip(bars, disp):
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 9, t,
            ha="center", va="bottom", fontsize=12, color=INK, fontweight="bold")
ax.set_ylim(0, 500)
ax.yaxis.grid(True, color=PURPLE_XL, linewidth=0.9, zorder=0)
ax.set_axisbelow(True)
for s in ["top", "right"]:
    ax.spines[s].set_visible(False)
for s in ["left", "bottom"]:
    ax.spines[s].set_color("#cccccc")
ax.tick_params(axis="x", labelsize=11.5, colors=INK, length=0)
ax.tick_params(axis="y", labelsize=9.5, colors=GRAY)
ax.set_title("开源矩阵影响力 · GitHub Stars", fontsize=17, color=INK,
             loc="left", pad=26, fontweight="bold")
ax.text(0, 1.015, "Open-source matrix across firefly-hefeng & abraxas914 — 800+ stars in total",
        transform=ax.transAxes, fontsize=9.5, color=GRAY)
ax.text(0.985, 0.90, "合计 800+ stars", transform=ax.transAxes, ha="right",
        fontsize=13, color=PURPLE, fontweight="bold")
fig.text(0.125, 0.015, "数据来源: GitHub (firefly-hefeng + abraxas914), 2026-10。VESTI 主仓为 360+。",
         fontsize=8.5, color=GRAY)
fig.tight_layout(rect=[0, 0.04, 1, 1])
fig.savefig(f"{OUT}/chart2_开源矩阵stars.png", facecolor="white")
plt.close(fig)

print("charts done")
