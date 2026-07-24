import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "..", "..", "..", "data", "sample", "세그먼트id별분포.csv")

# Korean-capable font (Windows system font fallback chain)
for cand in ["Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", "NanumGothic"]:
    if cand in {f.name for f in fm.fontManager.ttflist}:
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["axes.unicode_minus"] = False

df = pd.read_csv(SRC)
order = ["성별", "연령대", "거주", "제품 관심사", "콘텐츠 관심사", "기타"]

# validated categorical palette (dataviz skill, light-surface steps)
colors = {
    "성별": "#2a78d6",
    "연령대": "#eb6834",
    "거주": "#1baf7a",
    "제품 관심사": "#c98500",   # darker gold step for print-contrast (relief for low-contrast slot)
    "콘텐츠 관심사": "#d55181",  # darker magenta step for print-contrast
    "기타": "#008300",
}

expected_n = {"성별": 4, "연령대": 7, "거주": 241, "제품 관심사": 420, "콘텐츠 관심사": 184, "기타": 129}

rows = []
lorenz_data = {}
sorted_data = {}
for g in order:
    sub = df[df.feature_group == g].sort_values("device_cnt", ascending=False).reset_index(drop=True)
    n = len(sub)
    vals = sub.device_cnt.values.astype(float)
    mean = vals.mean()
    median = np.median(vals)
    std = vals.std(ddof=1) if n > 1 else 0.0
    cv = std / mean if mean else 0.0
    # CV's own ceiling depends on n: for a fixed-sum distribution over n bins, the most
    # extreme "winner takes all" case (one bin = total, rest = 0) yields sample CV = sqrt(n)
    # exactly. Raw CV is therefore NOT comparable across groups with very different n --
    # dividing by that ceiling gives a 0-1 "skew index" that IS comparable.
    cv_ceiling = np.sqrt(n)
    cv_normalized = cv / cv_ceiling if cv_ceiling else 0.0
    vmin, vmax = vals.min(), vals.max()
    top = sub.iloc[0]
    group_sum = vals.sum()
    top1_share_of_group = vals[0] / group_sum
    fair_share = 1.0 / n
    top1_concentration_ratio = top1_share_of_group / fair_share  # 1.0 = perfectly even, >1 = over-indexed
    rows.append(dict(
        feature_group=g, id_count=n, id_count_expected=expected_n[g],
        sum_device_cnt=int(group_sum), mean=round(mean, 1), median=round(median, 1),
        std=round(std, 1), cv=round(cv, 4), cv_ceiling_sqrt_n=round(cv_ceiling, 3),
        cv_normalized_0to1=round(cv_normalized, 4), min=int(vmin), max=int(vmax),
        top1_share_of_group_pct=round(top1_share_of_group * 100, 3),
        fair_share_pct_1_over_n=round(fair_share * 100, 3),
        top1_concentration_ratio_x=round(top1_concentration_ratio, 2),
        top_segment_name=top.segment_name, top_segment_id=int(top.segment_id), top_pct_of_total=top.pct_of_total_devices,
    ))
    cum = np.cumsum(vals) / vals.sum() * 100
    rank_pct = np.arange(1, n + 1) / n * 100
    lorenz_data[g] = (rank_pct, cum)
    sorted_data[g] = sub

summary = pd.DataFrame(rows)
summary.to_csv(os.path.join(BASE, "segment_group_summary_stats.csv"), index=False, encoding="utf-8-sig")
print(summary.to_string(index=False))

# ---- Chart 1: concentration / Lorenz-style overlay ----
fig, ax = plt.subplots(figsize=(8.5, 6), dpi=180)
ax.plot([0, 100], [0, 100], linestyle="--", linewidth=1.2, color="#c3c2b7", label="균등 분포(대각선)")
for g in order:
    rank_pct, cum = lorenz_data[g]
    ax.plot(rank_pct, cum, linewidth=2.2, color=colors[g], label=f"{g} (n={len(sorted_data[g])})")
ax.set_xlabel("ID 순위 누적 비율 (device_cnt 내림차순, %)")
ax.set_ylabel("누적 device_cnt 비율 (%)")
ax.set_title("그룹 간 쏠림 비교 — 누적 점유율 곡선\n대각선에서 멀리 휘어질수록 소수 ID에 쏠려 있음", fontsize=12, pad=14)
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.grid(True, linewidth=0.5, color="#e1e0d9")
ax.spines[["top", "right"]].set_visible(False)
ax.legend(loc="lower right", frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(BASE, "concentration_curve.png"))
plt.close(fig)

# ---- Chart 2: per-group distribution shape (log-y small multiples) ----
fig, axes = plt.subplots(2, 3, figsize=(13, 7.5), dpi=180)
for ax, g in zip(axes.flat, order):
    sub = sorted_data[g]
    n = len(sub)
    x = np.arange(1, n + 1)
    y = np.maximum(sub.device_cnt.values, 1)
    # x spacing is always 1 unit regardless of n (arange(1, n+1)) — width must NOT scale
    # with n. Previous version used 260/n, which blew up to ~65 at n=4 and made all bars
    # overlap into one solid block. A fixed width < 1 keeps a visible gap at any n.
    ax.bar(x, y, width=0.85, color=colors[g], linewidth=0)
    ax.set_yscale("log")
    ax.set_title(f"{g}  (n={n}, CV={summary.loc[summary.feature_group==g,'cv'].values[0]:.2f})", fontsize=10.5)
    ax.set_xticks([])
    ax.grid(True, which="major", axis="y", linewidth=0.4, color="#e1e0d9")
    ax.spines[["top", "right"]].set_visible(False)
    top = sub.iloc[0]
    ax.text(0.97, 0.93, f"1위: {top.segment_name} ({top.pct_of_total_devices}%)",
            transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#1b1b1b",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#e1e0d9", linewidth=0.8, alpha=0.92))
fig.suptitle("그룹별 분포 형태 (y축 로그 스케일, 그룹별 상대 스케일)", fontsize=13, y=1.02)
fig.tight_layout()
fig.savefig(os.path.join(BASE, "distribution_shape.png"), bbox_inches="tight")
plt.close(fig)

print("\nSaved: concentration_curve.png, distribution_shape.png, segment_group_summary_stats.csv")
