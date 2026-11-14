#!/usr/bin/env python3
"""
Plot Wiki-Evolve (GLM-5.2) vs all baselines — GLM-5.2 only (no DeepSeek-Pro).
6 games, 10 episodes. Red solid line for ours, colored dashed for baselines.
Standalone: all data hardcoded, no external dependencies beyond matplotlib+numpy.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# === Data ===

games = ['Detective', 'Library', 'Zork1', 'Zork3', 'Balances', 'Temple']

# Wiki-Evolve GLM-5.2 (abl19_glm52_full)
glm52 = {
    'Detective': [130, 210, 330, 340, 340, 310, 330, 310, 340, 330],
    'Library':   [21, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    'Zork1':     [54, 40, 74, 65, 75, 50, 0, 85, 99, 74],
    'Zork3':     [3, 3, 3, 3, 1, 4, 4, 5, 5, 5],
    'Balances':  [15, 20, 20, 20, 20, 20, 20, 20, 20, 20],
    'Temple':    [20, 5, 25, 25, 25, 25, 25, 20, 25, 25],
}

# Baselines (from EvoTest benchmark, first 10 episodes)
evotest_glm52 = {
    'Detective': [100, 100, 290, 290, 290, 290, 280, 280, 290, 290],
    'Library':   [0, 10, 10, 10, 10, 10, 12, 17, 19, 19],
    'Zork1':     [40, 50, 40, 50, 40, 50, 50, 50, 40, 50],
    'Zork3':     [3, 2, 2, 3, 2, 2, 3, 3, 3, 3],
    'Balances':  [15, 10, 15, 10, 20, 20, 20, 20, 20, 20],
    'Temple':    [8, 8, 8, 8, 8, 8, 8, 8, 8, 8],
}
evotest_gem = {
    'Detective': [20, 70, 320, 320, 320, 320, 320, 320, 330, 320],
    'Library':   [10, 10, 10, 10, 10, 17, 17, 19, 19, 19],
    'Zork1':     [10, 35, 25, 40, 35, 44, 35, 50, 35, 35],
    'Zork3':     [0, 0, 1, 3, 3, 3, 3, 3, 3, 3],
    'Balances':  [8, 8, 8, 8, 8, 8, 8, 8, 8, 8],
    'Temple':    [4, 4, 4, 4, 7, 7, 7, 7, 7, 7],
}
evoprompt = {
    'Detective': [20, 60, 90, 110, 150, 140, 180, 200, 220, 210],
    'Library':   [10, 11, 13, 12, 15, 14, 16, 13, 16, 13],
    'Zork1':     [10, 10, 15, 20, 20, 35, 25, 20, 30, 30],
    'Zork3':     [0, 1, 2, 1, 2, 2, 1, 2, 3, 2],
    'Balances':  [8, 8, 10, 10, 10, 10, 8, 10, 8, 8],
    'Temple':    [4, 7, 4, 7, 4, 9, 7, 4, 9, 7],
}
reflexion = {
    'Detective': [20, 110, 100, 120, 130, 120, 140, 150, 140, 160],
    'Library':   [10, 10, 12, 11, 13, 12, 14, 13, 15, 14],
    'Zork1':     [10, 15, 15, 10, 20, 20, 25, 25, 20, 25],
    'Zork3':     [0, 1, 1, 2, 1, 2, 1, 1, 2, 1],
    'Balances':  [8, 8, 10, 8, 8, 10, 8, 8, 8, 8],
    'Temple':    [4, 4, 7, 4, 7, 4, 7, 4, 7, 7],
}
grpo = {
    'Detective': [20, 30, 100, 90, 100, 40, 40, 40, 20, 60],
    'Library':   [10, 14, 11, 16, 12, 18, 10, 15, 11, 17],
    'Zork1':     [10, 10, 25, 10, 30, 10, 15, 10, 20, 10],
    'Zork3':     [0, 2, 1, 1, 0, 3, 0, 1, 0, 2],
    'Balances':  [8, 13, 8, 8, 8, 16, 10, 10, 8, 8],
    'Temple':    [4, 9, 4, 7, 4, 11, 4, 9, 4, 7],
}
memory = {
    'Detective': [20, 80, 70, 80, 90, 80, 90, 100, 90, 100],
    'Library':   [10, 10, 11, 11, 12, 12, 12, 11, 13, 13],
    'Zork1':     [10, 15, 15, 15, 15, 20, 20, 20, 20, 20],
    'Zork3':     [0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    'Balances':  [8, 8, 8, 10, 10, 10, 10, 10, 10, 10],
    'Temple':    [4, 4, 4, 7, 7, 7, 7, 7, 7, 7],
}
static = {
    'Detective': [20, 20, 30, 20, 20, 20, 20, 30, 20, 20],
    'Library':   [10, 10, 10, 10, 10, 10, 10, 10, 10, 10],
    'Zork1':     [10, 10, 10, 10, 10, 0, 10, 15, 10, 10],
    'Zork3':     [0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
    'Balances':  [8, 8, 3, 8, 8, 8, 8, 8, 8, 8],
    'Temple':    [4, 4, 4, 4, 4, 9, 4, 4, 4, 4],
}

# === Plot config ===

# Ours: solid red line with circle markers
ours = [
    ('Wiki-Evolve (GLM-5.2)', glm52, '#e74c3c', '-', 'o', 2.5),
]

# Baselines: dashed colored lines, no markers
baselines = [
    ('EvoTest (GLM-5.2)',    evotest_glm52, '#8e44ad', '--', 1.5),
    ('EvoTest (Gemini)',     evotest_gem,   '#2980b9', '--', 1.5),
    ('EvoPrompt (Gemini)',   evoprompt,     '#27ae60', '-.', 1.5),
    ('Reflexion (Gemini)',   reflexion,     '#d4a017', ':',  1.5),
    ('GRPO (Gemini)',        grpo,          '#16a085', (0,(5,2)), 1.5),
    ('Memory (Gemini)',      memory,        '#c0392b', (0,(3,1,1,1)), 1.5),
    ('Static (Gemini)',      static,        '#7f8c8d', (0,(1,1)), 1.5),
]

ncols, nrows = 3, 2
fig, axes = plt.subplots(nrows, ncols, figsize=(28, 14))
axes = axes.flatten()
episodes = np.arange(1, 11)

for i, game in enumerate(games):
    ax = axes[i]
    # Plot baselines (lower zorder)
    for label, data, color, ls, lw in baselines:
        ax.plot(episodes, data[game], color=color, linestyle=ls, linewidth=lw,
                marker='None', label=label, alpha=0.75, zorder=3)
    # Plot ours on top
    for label, data, color, ls, marker, lw in ours:
        ax.plot(episodes, data[game], color=color, linestyle=ls, linewidth=lw,
                marker=marker, markersize=6, label=label, zorder=5)
    ax.set_title(game, fontsize=16, fontweight='bold')
    ax.set_xlabel('Episode', fontsize=13)
    ax.set_ylabel('Score', fontsize=13)
    ax.set_xticks(episodes)
    ax.legend(fontsize=8, loc='lower right', framealpha=0.85, ncol=2)
    ax.grid(True, alpha=0.3)

fig.suptitle('Wiki-Evolve (GLM-5.2) vs All Baselines — First 10 Episodes', fontsize=20, fontweight='bold', y=1.01)
plt.tight_layout()
plt.savefig('comparison_glm52_only.png', dpi=150, bbox_inches='tight')
plt.savefig('comparison_glm52_only.pdf', bbox_inches='tight')
print("Saved comparison_glm52_only.png/pdf")

# Print summary table
max_scores = {'Detective': 360, 'Library': 30, 'Zork1': 350, 'Zork3': 7, 'Balances': 51, 'Temple': 35}
all_methods = [('Wiki-Evolve (GLM-5.2)', glm52, '#000', '-', '', 0)] + [(l, d, c, ls, lw, 0) for l, d, c, ls, lw in baselines]
print(f"\n{'Game':14s}", end='')
for label, _, _, _, _, _ in all_methods:
    print(f" | {label[:18]:>18s}", end='')
print()
print("-" * (14 + 21 * len(all_methods)))
for game in games:
    print(f"{game:14s}", end='')
    for label, data, _, _, _, _ in all_methods:
        avg = sum(data[game]) / 10
        pct = avg / max_scores[game] * 100
        print(f" | {avg:8.1f} ({pct:4.1f}%)", end='')
    print()
print("-" * (14 + 21 * len(all_methods)))
print(f"{'TOTAL avg':14s}", end='')
for label, data, _, _, _, _ in all_methods:
    total = sum(sum(data[g]) for g in games) / 60
    pcts = [sum(data[g]) / 10 / max_scores[g] * 100 for g in games]
    avg_pct = sum(pcts) / len(pcts)
    print(f" | {total:8.1f} ({avg_pct:4.1f}%)", end='')
print()
