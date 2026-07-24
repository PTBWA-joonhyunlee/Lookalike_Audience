import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import os

BASE = os.path.dirname(os.path.abspath(__file__))

for cand in ["Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", "NanumGothic"]:
    if cand in {f.name for f in fm.fontManager.ttflist}:
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["axes.unicode_minus"] = False

TRAINED = "#2a78d6"
DESIGNED = "#c98500"
NEUTRAL = "#5a5850"
FUSION = "#1baf7a"
BG_TRAINED = "#eaf1fb"
BG_DESIGNED = "#faf1de"
BG_NEUTRAL = "#f1f0eb"
BG_FUSION = "#e6f7f0"


def box(ax, x, y, w, h, text, edge=NEUTRAL, face="#ffffff", fontsize=9.5, weight="normal"):
    b = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.06",
        linewidth=1.4, edgecolor=edge, facecolor=face,
    )
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize,
            color="#1b1b1b", weight=weight, linespacing=1.4)
    return (x, y, w, h)


def arrow(ax, p1, p2, style="-", color=NEUTRAL, lw=1.5):
    a = FancyArrowPatch(
        p1, p2, arrowstyle="-|>", mutation_scale=14, linewidth=lw,
        color=color, linestyle=style, shrinkA=2, shrinkB=2,
    )
    ax.add_patch(a)


def right(b):
    x, y, w, h = b
    return (x + w, y + h / 2)


def left(b):
    x, y, w, h = b
    return (x, y + h / 2)


def top(b):
    x, y, w, h = b
    return (x + w / 2, y + h)


def bottom(b):
    x, y, w, h = b
    return (x + w / 2, y)


# ---- Diagram 1: overall embedding architecture ----
fig, ax = plt.subplots(figsize=(13, 7.5), dpi=180)
ax.set_xlim(0, 13)
ax.set_ylim(0, 7.5)
ax.axis("off")

ax.text(0.1, 7.2, "임베딩 아키텍처 개요 — 3개 입력 소스, 학습 상태는 색으로 구분", fontsize=13, weight="bold")
ax.add_patch(plt.Rectangle((0.1, 6.75), 0.3, 0.2, color=TRAINED))
ax.text(0.5, 6.85, "학습·검증 완료(addi 소스)", fontsize=9, va="center")
ax.add_patch(plt.Rectangle((4.6, 6.75), 0.3, 0.2, color=DESIGNED))
ax.text(5.0, 6.85, "피처 설계·검증 완료, 학습 코드 미통합(propfit 소스)", fontsize=9, va="center")

# lane 1: user_profile (trained)
src1 = box(ax, 0.3, 5.2, 2.6, 1.0, "bid log 프로필\n(01_pool_profile_apr_may.csv)", edge=TRAINED, face=BG_TRAINED)
enc1 = box(ax, 3.4, 5.2, 2.6, 1.0, "user_profile\nAutoencoder", edge=TRAINED, face=BG_TRAINED)
emb1 = box(ax, 6.5, 5.2, 1.8, 1.0, "임베딩\n64dim", edge=TRAINED, face=BG_TRAINED, weight="bold")
arrow(ax, right(src1), left(enc1), color=TRAINED)
arrow(ax, right(enc1), left(emb1), color=TRAINED)

# lane 2: media_sequence (trained)
src2 = box(ax, 0.3, 3.6, 2.6, 1.0, "bid log 미디어 방문\n(02_pool_media_apr_may.csv)", edge=TRAINED, face=BG_TRAINED)
enc2 = box(ax, 3.4, 3.6, 2.6, 1.0, "media_sequence\nSASRec(causal)", edge=TRAINED, face=BG_TRAINED)
emb2 = box(ax, 6.5, 3.6, 1.8, 1.0, "임베딩\n64dim", edge=TRAINED, face=BG_TRAINED, weight="bold")
arrow(ax, right(src2), left(enc2), color=TRAINED)
arrow(ax, right(enc2), left(emb2), color=TRAINED)

# fusion (trained)
fusion = box(ax, 9.0, 4.4, 2.0, 1.0, "Fusion MLP\n(concat 128→64→1)", edge=FUSION, face=BG_FUSION, weight="bold")
score = box(ax, 11.4, 4.4, 1.3, 1.0, "스코어\n(sigmoid)", edge=FUSION, face=BG_FUSION)
arrow(ax, right(emb1), (9.0, 4.9), color=TRAINED)
arrow(ax, right(emb2), (9.0, 4.9), color=TRAINED)
arrow(ax, right(fusion), left(score), color=FUSION)

# lane 3: segment_features (designed, not yet trained)
src3 = box(ax, 0.3, 1.1, 2.6, 1.4,
           "skp 세그먼트\n(11_user_embedding_features.sql)\n성별/연령대/거주/관심아 3그룹",
           edge=DESIGNED, face=BG_DESIGNED, fontsize=8.8)
enc3 = box(ax, 3.4, 1.1, 2.6, 1.4,
           "segment_features\n성별=스칼라, 연령대=원핫+UNK\n거주·관심아=BERT lookup\n+ EmbeddingBag(학습 시 pooling)",
           edge=DESIGNED, face=BG_DESIGNED, fontsize=8.3)
emb3 = box(ax, 6.5, 1.1, 1.8, 1.4, "피처 배열\n(dim 미정)", edge=DESIGNED, face=BG_DESIGNED, weight="bold")
arrow(ax, right(src3), left(enc3), color=DESIGNED)
arrow(ax, right(enc3), left(emb3), color=DESIGNED)
arrow(ax, right(emb3), (9.3, 4.4), style="--", color=DESIGNED)
ax.text(9.85, 3.55, "미통합\n(다음 시도 후보)", fontsize=8.3, color=DESIGNED, ha="center", style="italic")

fig.tight_layout()
fig.savefig(os.path.join(BASE, "embedding_architecture_overview.png"), bbox_inches="tight")
plt.close(fig)


# ---- Diagram 2: segment_features internal detail ----
fig, ax = plt.subplots(figsize=(13, 8.5), dpi=180)
ax.set_xlim(0, 13)
ax.set_ylim(0, 8.5)
ax.axis("off")
ax.text(0.1, 8.2, "segment_features 내부 구조 — querys/propfit/11_user_embedding_features.sql 출력부터", fontsize=13, weight="bold")

sql = box(ax, 4.3, 7.0, 4.4, 0.8, "11_user_embedding_features.sql\n(device_ifa 단위 원시 컬럼 7개)", edge=NEUTRAL, face=BG_NEUTRAL, weight="bold")

# left path: gender / age (simple, no BERT)
gender_src = box(ax, 0.3, 5.5, 2.6, 0.9, "gender_score\n(SQL에서 이미\n평균 계산된 스칼라)", edge=NEUTRAL, face="#ffffff", fontsize=8.6)
gender_dst = box(ax, 0.3, 4.2, 2.6, 0.7, "그대로 통과\n(-1.0 ~ +1.0)", edge=NEUTRAL, face="#ffffff", fontsize=8.6)
arrow(ax, bottom(sql), top(gender_src))
arrow(ax, bottom(gender_src), top(gender_dst))

age_src = box(ax, 3.2, 5.5, 2.6, 0.9, "age_bracket_ids\n(첫 값만 사용,\navg_matched~1.04)", edge=NEUTRAL, face="#ffffff", fontsize=8.6)
age_dst = box(ax, 3.2, 4.2, 2.6, 0.7, "CategoryVocab\n원핫 (0=NA,1=UNK)", edge=NEUTRAL, face="#ffffff", fontsize=8.6)
arrow(ax, bottom(sql), top(age_src))
arrow(ax, bottom(age_src), top(age_dst))

# right path: 4 pooled groups sharing one BERT lookup
group_labels = ["residence_ids\n(max_len=72)", "product_interest_ids\n(max_len=24)",
                "content_interest_ids\n(max_len=48)", "etc_segment_ids\n(max_len=48)"]
group_boxes = []
gx = 6.6
for label in group_labels:
    b = box(ax, gx, 5.5, 1.5, 0.9, label, edge=DESIGNED, face=BG_DESIGNED, fontsize=7.6)
    arrow(ax, bottom(sql), top(b), color=DESIGNED)
    group_boxes.append(b)
    gx += 1.55

enc_box = box(ax, 6.6, 4.2, 5.9, 0.7, "pooling.encode_padded_ids → 그룹별 고정 길이 인덱스 배열(패딩=0)", edge=DESIGNED, face=BG_DESIGNED, fontsize=8.8)
for b in group_boxes:
    arrow(ax, bottom(b), (b[0] + b[2] / 2, 4.9), color=DESIGNED)

lookup = box(ax, 6.6, 2.8, 2.7, 0.9, "segment_bert_lookup.npz\n(1,049 x 768,\nko-sroberta-multitask)", edge=DESIGNED, face=BG_DESIGNED, fontsize=8.3)
arrow(ax, (8.0, 4.2), (8.0, 3.7), color=DESIGNED)
ax.text(8.6, 3.9, "초기 가중치로 사용", fontsize=7.8, color=DESIGNED, style="italic")

embbag = box(ax, 9.8, 2.8, 2.7, 0.9, "nn.EmbeddingBag\n(padding_idx=0, mode=mean)\n— 학습 시 배치 단위 pooling", edge=DESIGNED, face=BG_DESIGNED, fontsize=8.3, weight="bold")
arrow(ax, right(lookup), left(embbag), color=DESIGNED)
arrow(ax, bottom(enc_box), top(embbag), color=DESIGNED)

out = box(ax, 9.8, 1.4, 2.7, 0.9, "그룹별 pooled 벡터\n(768dim x 4그룹)", edge=DESIGNED, face=BG_DESIGNED, weight="bold")
arrow(ax, bottom(embbag), top(out), color=DESIGNED)

# storage callout
callout = box(ax, 0.3, 0.2, 12.4, 1.0,
              "저장 용량(1% 표본, 53만 건): 디바이스별 dense pooled 벡터를 미리 저장 -> 6.27GB"
              "  =>  인덱스 배열만 저장(pooling은 학습 시 계산) -> 806.5MB (7.8배 감소)\n"
              "전체 모집단(5,330만 명, 약 100배) 환산 시 dense 방식은 약 627GB로 저장 불가능 -- 그래서 인덱스 배열 방식으로 전환",
              edge="#b23b3b", face="#fbeaea", fontsize=8.6)

fig.tight_layout()
fig.savefig(os.path.join(BASE, "segment_features_detail.png"), bbox_inches="tight")
plt.close(fig)


# ---- Diagram 3: segment_features embedding model (encoder/decoder, proposed — 미학습) ----
# 오프라인 전처리(segment_id -> 텍스트 -> BERT)를 별도 패널로 안 빼고, 그 결과를 쓰는
# 공유 EmbeddingBag 박스 바로 옆에 사이드 인셋으로 붙여 하나의 아키텍처로 보이게 한다.
fig, ax = plt.subplots(figsize=(17.2, 11.5), dpi=180)
ax.set_xlim(0, 17.2)
ax.set_ylim(0, 11.5)
ax.axis("off")
ax.text(0.1, 11.2, "segment_features 임베딩 모델(제안, 미학습) — user_profile Autoencoder와 동일 패턴", fontsize=13, weight="bold")

cols_x = [0.2, 2.25, 4.30, 6.35, 8.40, 10.45]
col_w = 1.85
input_labels = [
    "gender_score\n(스칼라)",
    "age_bracket_idx",
    "residence_idx\n(max_len=72)",
    "product_interest_idx\n(max_len=24)",
    "content_interest_idx\n(max_len=48)",
    "etc_segment_idx\n(max_len=48)",
]
input_boxes = [box(ax, x, 9.9, col_w, 0.8, lbl, edge=NEUTRAL, face=BG_NEUTRAL, fontsize=8.2) for x, lbl in zip(cols_x, input_labels)]

# row 2: per-field processing
gender_proc = box(ax, cols_x[0], 8.6, col_w, 0.7, "그대로 사용\n(1dim)", edge=NEUTRAL, face="#ffffff", fontsize=8.2)
age_proc = box(ax, cols_x[1], 8.6, col_w, 0.7, "nn.Embedding\n(8dim)", edge=NEUTRAL, face="#ffffff", fontsize=8.2)
arrow(ax, bottom(input_boxes[0]), top(gender_proc))
arrow(ax, bottom(input_boxes[1]), top(age_proc))

shared_bag = box(ax, cols_x[2], 8.6, cols_x[5] + col_w - cols_x[2], 0.7,
                  "공유 nn.EmbeddingBag(1,050 x 768, padding_idx=0, mode=mean)\n"
                  "idx로 벡터를 '조회'만 함 — 벡터 자체는 오른쪽 오프라인 단계에서 만들어짐",
                  edge=DESIGNED, face=BG_DESIGNED, fontsize=8.2, weight="bold")
for b in input_boxes[2:]:
    arrow(ax, bottom(b), (b[0] + b[2] / 2, 9.3), color=DESIGNED)

# ---- side inset: 오프라인 전처리(segment_id -> 텍스트 -> BERT) — shared_bag 오른쪽에 바로 연결 ----
side_x = cols_x[5] + col_w + 0.5   # shared_bag 오른쪽 끝 + 여백
side_w = 17.2 - side_x - 0.2
ax.add_patch(plt.Rectangle((side_x - 0.2, 7.55), side_w + 0.4, 3.45, linewidth=1.1, linestyle="--", edgecolor=DESIGNED, facecolor="#fffdf7"))
ax.text(side_x - 0.1, 10.75, "오프라인, 최초 1회(taxonomy 안 바뀌면 재실행 불필요)", fontsize=7.8, color=DESIGNED, weight="bold")

seg_id_box = box(ax, side_x, 9.85, side_w, 0.6, "segment_id '27533'\n(1,049개 taxonomy 중 하나)", edge=DESIGNED, face="#ffffff", fontsize=7.6)
text_box = box(ax, side_x, 8.75, side_w, 0.6, "세그먼트_카테고리.csv 조회 →\n\"거주지(도)>경기도\" 텍스트", edge=DESIGNED, face="#ffffff", fontsize=7.4)
bert_box = box(ax, side_x, 7.7, side_w, 0.75, "SentenceTransformer(ko-sroberta)\n→ 768dim 벡터, lookup 762번 행에 저장", edge=DESIGNED, face=BG_DESIGNED, fontsize=7.4, weight="bold")
arrow(ax, bottom(seg_id_box), top(text_box), color=DESIGNED)
arrow(ax, bottom(text_box), top(bert_box), color=DESIGNED)
# 오프라인에서 만든 벡터가 왼쪽 공유 EmbeddingBag의 가중치로 들어감(같은 lookup 파일)
arrow(ax, left(bert_box), right(shared_bag), color=DESIGNED, lw=1.8)

# row 3: per-group projection (768 -> small dim)
proj_dims = [32, 16, 16, 16]
proj_labels = [f"Linear(768→{d})\n({name})" for d, name in zip(proj_dims, ["residence", "product", "content", "etc"])]
proj_boxes = []
for x, lbl in zip(cols_x[2:], proj_labels):
    b = box(ax, x, 7.3, col_w, 0.8, lbl, edge=DESIGNED, face=BG_DESIGNED, fontsize=8.2)
    arrow(ax, (x + col_w / 2, 8.6), top(b), color=DESIGNED)
    proj_boxes.append(b)

# row 4: concat
concat = box(ax, 0.2, 6.0, 12.1, 0.8,
             "concat: gender(1) + age_embed(8) + residence_proj(32) + product_proj(16) + content_proj(16) + etc_proj(16) = 89dim",
             edge=NEUTRAL, face=BG_NEUTRAL, fontsize=9.2, weight="bold")
arrow(ax, bottom(gender_proc), (1.1, 6.8))
arrow(ax, bottom(age_proc), (3.2, 6.8))
for b in proj_boxes:
    arrow(ax, bottom(b), (b[0] + b[2] / 2, 6.8), color=DESIGNED)

# row 5: encoder MLP -> z
enc1 = box(ax, 3.0, 4.7, 2.6, 0.8, "Linear(89→64)\n→ ReLU", edge=NEUTRAL, face="#ffffff", fontsize=9)
enc2 = box(ax, 6.0, 4.7, 2.6, 0.8, "Linear(64→32)", edge=NEUTRAL, face="#ffffff", fontsize=9)
z = box(ax, 9.0, 4.5, 3.1, 1.2, "z = segment_features\n임베딩 (32dim)", edge=FUSION, face=BG_FUSION, fontsize=11, weight="bold")
arrow(ax, bottom(concat), top(enc1))
arrow(ax, right(enc1), left(enc2))
arrow(ax, right(enc2), left(z))

# decoder (training-only, dashed section)
ax.add_patch(plt.Rectangle((0.15, 0.15), 12.7, 3.6, linewidth=1.2, linestyle="--", edgecolor=NEUTRAL, facecolor="none"))
ax.text(0.3, 3.55, "디코더 — 학습에만 사용, 인코더 출력(z)만 임베딩으로 남기고 추론 시 버림(§1 user_profile과 동일)", fontsize=9, color=NEUTRAL, style="italic")

dec1 = box(ax, 9.4, 2.4, 2.6, 0.8, "Linear(32→64)\n→ ReLU", edge=NEUTRAL, face="#ffffff", fontsize=9)
arrow(ax, bottom(z), top(dec1), style="--")

heads = box(ax, 0.4, 0.5, 11.6, 1.5,
            "필드별 복원 헤드\n"
            "gender: Linear(64→1) → MSE(vs gender_score)     age: Linear(64→age_vocab) → CrossEntropy(vs age_bracket_idx)\n"
            "residence/product/content/etc: Linear(64→proj_dim) → MSE(vs 인코더의 해당 projection 출력)",
            edge=NEUTRAL, face="#ffffff", fontsize=8.6)
arrow(ax, left(dec1), (heads[0] + heads[2], heads[1] + heads[3] * 0.75), style="--")

fig.tight_layout()
fig.savefig(os.path.join(BASE, "segment_features_model.png"), bbox_inches="tight")
plt.close(fig)

print("saved: embedding_architecture_overview.png, segment_features_detail.png, segment_features_model.png")
