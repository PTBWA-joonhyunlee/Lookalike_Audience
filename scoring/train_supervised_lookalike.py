# scoring/train_supervised_lookalike.py
#
# 첫 백테스트(docs/_archive/audience_embedding_plan_full.md §7-6)에서 시드 centroid
# 코사인 유사도(unsupervised) 방식이 최하위 10%는 잘 걸러내지만 나머지 90% 안에서는 점수가
# 순위를 못 매기는 문제가 확인됐다. 시드(양성 라벨) 여부를 1/0 라벨로 삼아 128차원 fused
# 임베딩(user_profile+media_sequence concat) 위에 작은 분류기를 지도학습시켜, "이 유저 프로필이
# 시드와 얼마나 비슷한 패턴인가"를 직접 예측하게 한다 — centroid까지의 단일 방향 거리보다
# 표현력이 높다(비선형 결합 가능).
#
# 임베딩 자체(user_profile/media_sequence)는 재학습하지 않는다 — 그 위에 얹는 얕은 분류기만
# 학습해서 아티팩트(model.pt, meta.json)로 저장한다. 학습된 분류기로 신규 유저를 스코어링하려면
# infer_supervised_lookalike.py를 쓴다.
#
# 불균형 처리(2026-07-09 개정, docs/_archive/202607091533.md 후속): 시드 정의를 postback
# tier에서 IP 매칭 전환으로 바꾸면서 양성 비율이 4~5%(T2+)에서 0.01~0.17% 수준으로 극단적으로
# 낮아졌다. 이 정도 희소성에서는 pos_weight만으로는 부족하다 — 순수 랜덤 배치의 대부분이
# 양성 0건이라 학습 신호 자체가 너무 드물다. 그래서:
#   1) 배치마다 양성을 강제로 섞는 층화 미니배치 샘플링(--pos-frac, 양성은 복원추출)
#   2) pos_weight는 원본 pos_rate가 아니라 이 층화된 배치 구성 비율(pos_frac)을 기준으로 계산
#   3) train/val 분할도 라벨 기준 층화(val에 양성이 0건 나오는 사고 방지)
#   4) 평가지표를 rank AUC 하나가 아니라 PR-AUC(average precision)·top-K% recall도 같이 출력
#      — 극단적 불균형에서는 AUC가 여전히 높게 나올 수 있어(음성이 압도적으로 많아 하위권만
#      잘 걸러도 AUC가 오름) 실제 타겟팅 관점(상위 K% 안에 양성을 얼마나 담는지)을 추가로 봐야 함
#
# CLI:
#   .venv\Scripts\python.exe -m scoring.train_supervised_lookalike \
#     --pool-profile-emb data/embeddings/pool_profile_stratified.csv \
#     --pool-media-emb data/embeddings/pool_media_stratified.csv \
#     --seed-ids data/raw/03_seed_users_apr_may.csv \
#     --model-out data/models/fusion_classifier
#
# --config: 위 옵션들을 담은 JSON 설정 파일 (config/train_supervised_lookalike.example.json
#   참고). 개별 CLI 옵션을 같이 주면 그 값이 config보다 우선한다.

import argparse

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from scoring.fusion_classifier import FusionClassifier, save_artifacts
from scoring.fused_embeddings import ID_COL, load_fused_embeddings
from scoring.train_config import load_train_config


def _rank_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """sklearn 의존 없이 rank-sum 공식으로 AUC 계산 (동점 처리를 위해 평균 순위 사용)."""
    n_pos = labels.sum()
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores)
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    # 동점 구간은 평균 순위로 보정
    _, inv, counts = np.unique(scores, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inv, ranks)
    avg_rank = (sums / counts)[inv]
    rank_sum_pos = avg_rank[labels == 1].sum()
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _average_precision(scores: np.ndarray, labels: np.ndarray) -> float:
    """PR-AUC(average precision) — sklearn 없이 직접 계산. 극단적 불균형에서는 rank AUC보다
    "상위권에 양성이 얼마나 몰려 있는가"를 더 직접적으로 반영한다."""
    n_pos = labels.sum()
    if n_pos == 0:
        return float("nan")
    order = np.argsort(-scores)  # 점수 내림차순
    labels_sorted = labels[order]
    tp_cumsum = np.cumsum(labels_sorted)
    precision_at_k = tp_cumsum / np.arange(1, len(labels_sorted) + 1)
    return float((precision_at_k * labels_sorted).sum() / n_pos)


def _topk_recall(scores: np.ndarray, labels: np.ndarray, pct: float = 0.1) -> float:
    """상위 pct 비율 안에 실제 양성 중 몇 %가 들어오는지(recall@top-K%). 실무에서 "상위 K%만
    타겟팅하면 전환자를 얼마나 놓치지 않는가"에 바로 대응하는 지표."""
    n_pos = labels.sum()
    if n_pos == 0:
        return float("nan")
    k = max(1, int(np.ceil(len(scores) * pct)))
    top_idx = np.argsort(-scores)[:k]
    return float(labels[top_idx].sum() / n_pos)


def _stratified_split(y: np.ndarray, val_frac: float, rng: np.random.RandomState):
    """라벨 기준으로 따로 섞은 뒤 val_frac씩 떼어 합친다 — 순수 랜덤 분할은 양성이 희소할 때
    val에 양성이 0건(또는 극소수) 걸릴 위험이 커서 val_auc/PR-AUC가 아예 계산 불가능해지거나
    표본 1~2개짜리 지표가 되기 쉽다. 양성/음성 각각 최소 1건은 val에 남도록 보정한다."""
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    rng.shuffle(pos_idx)
    rng.shuffle(neg_idx)

    n_val_pos = min(len(pos_idx), max(1, int(round(len(pos_idx) * val_frac)))) if len(pos_idx) > 0 else 0
    n_val_neg = max(1, int(round(len(neg_idx) * val_frac)))

    val_idx = np.concatenate([pos_idx[:n_val_pos], neg_idx[:n_val_neg]])
    train_idx = np.concatenate([pos_idx[n_val_pos:], neg_idx[n_val_neg:]])
    return train_idx, val_idx


def _iter_balanced_batches(pos_idx: np.ndarray, neg_idx: np.ndarray, batch_size: int, pos_frac: float, rng: np.random.RandomState):
    """배치마다 pos_frac 비율만큼 양성을 강제로 섞는다(양성은 복원추출 — 절대 수가 너무 적어
    비복원으로는 한 epoch도 못 채움). 음성은 매 epoch 셔플 후 비복원으로 소진해서 최대한
    전체 negative pool을 골고루 본다."""
    if len(pos_idx) == 0:
        n_neg_per_batch = batch_size
        n_pos_per_batch = 0
    else:
        n_pos_per_batch = max(1, int(round(batch_size * pos_frac)))
        n_neg_per_batch = batch_size - n_pos_per_batch

    neg_perm = rng.permutation(neg_idx)
    n_batches = max(1, len(neg_perm) // n_neg_per_batch)
    for i in range(n_batches):
        neg_batch = neg_perm[i * n_neg_per_batch : (i + 1) * n_neg_per_batch]
        if n_pos_per_batch > 0:
            pos_batch = rng.choice(pos_idx, size=n_pos_per_batch, replace=True)
            batch = np.concatenate([pos_batch, neg_batch])
        else:
            batch = neg_batch
        rng.shuffle(batch)
        yield batch


def train_classifier(
    pool_df: pd.DataFrame,
    seed_ids: set,
    id_col: str = ID_COL,
    num_epochs: int = 20,
    batch_size: int = 512,
    lr: float = 1e-3,
    val_frac: float = 0.1,
    hidden_dim: int = 64,
    pos_frac: float = 0.1,
    topk_pct: float = 0.1,
    seed: int = 42,
) -> FusionClassifier:
    emb_cols = [c for c in pool_df.columns if c != id_col]
    X = pool_df[emb_cols].to_numpy(dtype=np.float32)
    y = pool_df[id_col].astype(str).isin(seed_ids).to_numpy().astype(np.float32)
    print(f"[INFO] 학습 데이터 {len(y):,}명, 양성(시드) {int(y.sum()):,}명 ({y.mean():.4%})")

    rng = np.random.RandomState(seed)
    train_idx, val_idx = _stratified_split(y, val_frac, rng)
    print(
        f"[INFO] 라벨 층화 분할: train {len(train_idx):,}명(양성 {int(y[train_idx].sum())}) / "
        f"val {len(val_idx):,}명(양성 {int(y[val_idx].sum())})"
    )

    X_train, y_train = X[train_idx], y[train_idx]
    X_val_t = torch.from_numpy(X[val_idx])
    y_val_np = y[val_idx]

    train_pos_idx = np.where(y_train == 1)[0]
    train_neg_idx = np.where(y_train == 0)[0]

    # pos_weight는 원본 pos_rate가 아니라 배치 안에서 실제로 보게 될 pos_frac 기준으로 잡는다
    # (배치 구성 자체가 이미 층화됐으므로, 손실 가중치도 그 구성에 맞춰야 이중으로 과도하게
    # 양성을 밀어붙이지 않는다). 양성이 아예 없으면 가중치 불필요.
    effective_pos_frac = pos_frac if len(train_pos_idx) > 0 else max(y_train.mean(), 1e-6)
    pos_weight = torch.tensor([(1 - effective_pos_frac) / effective_pos_frac])

    model = FusionClassifier(in_dim=X.shape[1], hidden_dim=hidden_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    X_train_t = torch.from_numpy(X_train)
    y_train_t = torch.from_numpy(y_train)

    for epoch in range(1, num_epochs + 1):
        model.train()
        total_loss = 0.0
        n_seen = 0
        for batch_idx in _iter_balanced_batches(train_pos_idx, train_neg_idx, batch_size, pos_frac, rng):
            xb, yb = X_train_t[batch_idx], y_train_t[batch_idx]
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(batch_idx)
            n_seen += len(batch_idx)
        train_loss = total_loss / max(n_seen, 1)

        model.eval()
        with torch.no_grad():
            val_probs = torch.sigmoid(model(X_val_t)).numpy()
        val_auc = _rank_auc(val_probs, y_val_np)
        val_ap = _average_precision(val_probs, y_val_np)
        val_topk_recall = _topk_recall(val_probs, y_val_np, pct=topk_pct)
        print(
            f"[epoch {epoch}/{num_epochs}] train_loss={train_loss:.4f} "
            f"val_auc={val_auc:.4f} val_pr_auc={val_ap:.4f} "
            f"val_recall@top{topk_pct:.0%}={val_topk_recall:.4f}"
        )

    return model


def main():
    parser = argparse.ArgumentParser(description="시드 라벨로 fused 임베딩 위에 지도학습 분류기를 학습하고 저장한다.")
    parser.add_argument("--pool-profile-emb")
    parser.add_argument("--pool-media-emb")
    parser.add_argument("--seed-ids")
    parser.add_argument("--model-out", help="학습된 분류기 아티팩트(model.pt, meta.json) 저장 경로")
    parser.add_argument("--id-col", default=None)
    parser.add_argument("--num-epochs", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--learning-rate", type=float, default=None)
    parser.add_argument(
        "--pos-frac",
        type=float,
        default=None,
        help="극단적 불균형 대응: 학습 배치마다 강제로 채울 양성 비율(양성은 복원추출). 기본 0.1",
    )
    parser.add_argument(
        "--topk-pct",
        type=float,
        default=None,
        help="val_recall@top-K%% 리포트용 K 비율(0~1). 기본 0.1(상위 10%%)",
    )
    parser.add_argument(
        "--config",
        help="pool_profile_emb/pool_media_emb/seed_ids/model_out/id_col/num_epochs/batch_size/"
        "learning_rate/pos_frac/topk_pct를 담은 JSON 설정 파일 "
        "(config/train_supervised_lookalike.example.json 참고). 개별 CLI 옵션을 "
        "같이 주면 그 값이 config보다 우선한다.",
    )
    args = parser.parse_args()

    cfg = load_train_config(args.config) if args.config else {}
    pool_profile_emb = args.pool_profile_emb or cfg.get("pool_profile_emb")
    pool_media_emb = args.pool_media_emb or cfg.get("pool_media_emb")
    seed_ids_path = args.seed_ids or cfg.get("seed_ids")
    model_out = args.model_out or cfg.get("model_out")
    id_col = args.id_col or cfg.get("id_col", ID_COL)
    num_epochs = args.num_epochs if args.num_epochs is not None else cfg.get("num_epochs", 20)
    batch_size = args.batch_size if args.batch_size is not None else cfg.get("batch_size", 512)
    lr = args.learning_rate if args.learning_rate is not None else cfg.get("learning_rate", 1e-3)
    pos_frac = args.pos_frac if args.pos_frac is not None else cfg.get("pos_frac", 0.1)
    topk_pct = args.topk_pct if args.topk_pct is not None else cfg.get("topk_pct", 0.1)

    missing = [
        name
        for name, val in [
            ("--pool-profile-emb", pool_profile_emb),
            ("--pool-media-emb", pool_media_emb),
            ("--seed-ids", seed_ids_path),
            ("--model-out", model_out),
        ]
        if not val
    ]
    if missing:
        parser.error(f"{', '.join(missing)}을(를) 주거나 --config에 해당 키를 지정해야 한다.")

    pool_df = load_fused_embeddings(pool_profile_emb, pool_media_emb, id_col)
    print(f"[INFO] pool fused 임베딩: {len(pool_df):,}명, 차원 {pool_df.shape[1] - 1}")

    seed_ids = set(pd.read_csv(seed_ids_path)[id_col].astype(str))
    model = train_classifier(
        pool_df,
        seed_ids,
        id_col=id_col,
        num_epochs=num_epochs,
        batch_size=batch_size,
        lr=lr,
        pos_frac=pos_frac,
        topk_pct=topk_pct,
    )

    save_artifacts(model, model_out)


if __name__ == "__main__":
    main()
