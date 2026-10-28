# -*- coding: utf-8 -*-
"""性能图表面板, 两个尺寸: 竖版海报用 2020x760, 宽版海报用 2900x520
深紫=内部实测; 浅紫带* = 参照公开评测协议(NIAH/RULER/LoCoMo/LongMemEval)的内部口径估计值
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
PURPLE_XL = "#eee6f6"
INK = "#1a1a1a"
GRAY = "#777777"

rows = [
    ("VESTI 记忆底座 · Recall@5",   1.000, True,  "1.000"),
    ("针尖检索 · NIAH*",            1.000, False, "1.00"),
    ("长上下文检索 · RULER*",       0.970, False, "0.97"),
    ("长期对话记忆 · LoCoMo*",      0.940, False, "0.94"),
    ("制度智枢 · Recall@5",         0.926, True,  "0.926"),
    ("记忆一致性 · LongMemEval*",   0.920, False, "0.92"),
    ("制度智枢 · MRR",              0.737, True,  "0.737"),
]
FOOT = ("内部评测口径, 参照对应公开评测协议 (NIAH / RULER / LoCoMo / LongMemEval) · "
        "深紫 = 内部实测, 浅紫 * = 协议口径估计 · 2026-10")

def render(figsize, path, ylab_size, val_size, foot_size):
    labels = [r[0] for r in rows][::-1]
    vals = [r[1] for r in rows][::-1]
    cols = [PURPLE if r[2] else PURPLE_L for r in rows][::-1]
    txts = [r[3] for r in rows][::-1]
    fig, ax = plt.subplots(figsize=figsize, dpi=200)
    bars = ax.barh(labels, vals, color=cols, height=0.62, zorder=3)
    for b, t in zip(bars, txts):
        ax.text(b.get_width() + 0.012, b.get_y() + b.get_height() / 2, t,
                va="center", ha="left", fontsize=val_size, color=INK, fontweight="bold")
    ax.set_xlim(0, 1.13)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.xaxis.grid(True, color=PURPLE_XL, linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color("#d5d5d5")
    ax.tick_params(axis="y", labelsize=ylab_size, colors=INK, length=0)
    ax.tick_params(axis="x", labelsize=val_size - 2, colors=GRAY)
    fig.text(0.12, 0.035, FOOT, fontsize=foot_size, color=GRAY)
    fig.tight_layout(rect=[0, 0.10, 1, 1])
    fig.savefig(path, facecolor="white")
    plt.close(fig)

render((10.1, 3.4), f"{OUT}/panel_性能指标.png", 12, 11.5, 8.5)        # 2020x680
render((14.5, 2.15), f"{OUT}/panel_性能指标_wide.png", 12, 11, 9)       # 2900x430
print("panels done")
