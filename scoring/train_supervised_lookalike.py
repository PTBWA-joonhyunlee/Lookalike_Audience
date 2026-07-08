# scoring/train_supervised_lookalike.py
#
# scoring/lookalike.py(시드 centroid 코사인 유사도)의 지도학습 버전. 첫 백테스트(addi_data_
# embedding docs/audience_embedding_plan.md §7-6)에서 unsupervised centroid가 최하위 10%는
# 잘 걸러내지만 나머지 90% 안에서는 점수가 순위를 못 매기는 문제가 확인됐다. 시드(과거 관심
# 유저) 여부를 1/0 라벨로 삼아 128차원 fused 임베딩(user_profile+media_sequence concat) 위에
# 작은 분류기를 지도학습시켜, "이 유저 프로필이 시드와 얼마나 비슷한 패턴인가"를 직접 예측하게
# 한다 — centroid까지의 단일 방향 거리보다 표현력이 높다(비선형 결합 가능).
#
# 임베딩 자체(user_profile/media_sequence)는 재학습하지 않는다 — 그 위에 얹는 얕은 분류기만
# 학습해서 아티팩트(model.pt, meta.json)로 저장한다. 학습된 분류기로 신규 유저를 스코어링하려면
# infer_supervised_lookalike.py를 쓴다. 시드 비율이 낮아(파일럿 기준 pool의 ~4~5%)
# BCEWithLogitsLoss에 pos_weight로 클래스 불균형을 보정한다.
#
# CLI:
#   .venv\Scripts\python.exe -m scoring.train_supervised_lookalike \
#     --pool-profile-emb data/embeddings/user_profile_apr_may.csv \
#     --pool-media-emb data/embeddings/media_sequence_apr_may.csv \
#     --seed-ids data/raw/03_seed_interested_users_apr_may.csv \
#     --model-out data/models/fusion_classifier_addi
#
# --config: 위 옵션들을 담은 JSON 설정 파일 (config/train_supervised_lookalike.example.json
#   참고). 개별 CLI 옵션을 같이 주면 그 값이 config보다 우선한다.

import argparse

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from scoring.fusion_classifier import FusionClassifier, save_artifacts
from scoring.lookalike import ID_COL, load_fused_embeddings
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


def train_classifier(
    pool_df: pd.DataFrame,
    seed_ids: set,
    id_col: str = ID_COL,
    num_epochs: int = 20,
    batch_size: int = 512,
    lr: float = 1e-3,
    val_frac: float = 0.1,
    hidden_dim: int = 64,
    seed: int = 42,
) -> FusionClassifier:
    emb_cols = [c for c in pool_df.columns if c != id_col]
    X = pool_df[emb_cols].to_numpy(dtype=np.float32)
    y = pool_df[id_col].astype(str).isin(seed_ids).to_numpy().astype(np.float32)
    print(f"[INFO] 학습 데이터 {len(y):,}명, 양성(시드) {int(y.sum()):,}명 ({y.mean():.2%})")

    rng = np.random.RandomState(seed)
    idx = rng.permutation(len(y))
    n_val = int(len(y) * val_frac)
    val_idx, train_idx = idx[:n_val], idx[n_val:]

    X_train_t = torch.from_numpy(X[train_idx])
    y_train_t = torch.from_numpy(y[train_idx])
    X_val_t = torch.from_numpy(X[val_idx])
    y_val_np = y[val_idx]

    pos_rate = max(y_train_t.mean().item(), 1e-6)
    pos_weight = torch.tensor([(1 - pos_rate) / pos_rate])

    model = FusionClassifier(in_dim=X.shape[1], hidden_dim=hidden_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    n = len(X_train_t)
    for epoch in range(1, num_epochs + 1):
        model.train()
        perm = torch.randperm(n)
        total_loss = 0.0
        for start in range(0, n, batch_size):
            batch_idx = perm[start : start + batch_size]
            xb, yb = X_train_t[batch_idx], y_train_t[batch_idx]
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(batch_idx)
        train_loss = total_loss / n

        model.eval()
        with torch.no_grad():
            val_probs = torch.sigmoid(model(X_val_t)).numpy()
        val_auc = _rank_auc(val_probs, y_val_np)
        print(f"[epoch {epoch}/{num_epochs}] train_loss={train_loss:.4f} val_auc={val_auc:.4f} (0.5=무작위, 1.0=완벽)")

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
        "--config",
        help="pool_profile_emb/pool_media_emb/seed_ids/model_out/id_col/num_epochs/batch_size/learning_rate를 "
        "담은 JSON 설정 파일 (config/train_supervised_lookalike.example.json 참고). 개별 CLI 옵션을 "
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
    )

    save_artifacts(model, model_out)


if __name__ == "__main__":
    main()
