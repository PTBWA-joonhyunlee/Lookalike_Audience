# seed/scoring/train_multilabel.py
#
# 서로 겹치는 seed 여러 개를 멀티라벨(멀티헤드) 분류기 하나로 같이 학습한다
# (config.MULTILABEL_VARIANTS). seed별 이진 분류기(train_lookalike.py)와 입력(segment
# 임베딩 32dim)/pool은 같고, 출력만 라벨별 로짓 여러 개다.
#
# 클래스 불균형: 이진 분류기는 WeightedRandomSampler를 쓰지만, 멀티핫 라벨은 "샘플 하나의
# 클래스"가 정의되지 않아 샘플러로 균형을 맞추기 어렵다 — 대신 헤드별 pos_weight
# (= 그 라벨의 음성 수 / 양성 수, train split 기준)를 BCEWithLogitsLoss에 준다. 이 때문에
# 출력 확률은 보정(calibrated)돼 있지 않다 — 라벨 안에서의 순위는 의미 있지만 라벨 간
# 원점수 비교는 의미 없으므로, 추론 결과에는 라벨별 백분위(pct_<key>)를 같이 낸다.
#
# 검증 지표(라벨별):
#   - auc_vs_pool: 그 라벨 seed vs pool에만 있는 유저(라벨 전부 0) — seed별 이진 분류기와
#     같은 조건이라 기존 모델과 비교할 때 쓴다.
#   - auc_vs_rest: 그 라벨 seed vs 나머지 전부(다른 seed 포함) — 비슷한 seed끼리를 얼마나
#     구분하는지.
# 에폭마다 auc_vs_pool 평균이 가장 높았던 가중치를 저장한다.
#
# 실행(seed/ 안에서 cd 후): ..\.venv\Scripts\python.exe -m scoring.train_multilabel --variant military

import argparse
import copy
import json

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Subset

from embedding.common.device import resolve_device
from . import config
from .dataset import MultiLabelDataset, build_multilabel_frame, load_embeddings
from .model import MultiHeadLookalikeClassifier


def _val_metrics(scores: np.ndarray, labels: np.ndarray, label_keys) -> dict:
    pool_only = labels.sum(axis=1) == 0
    out = {}
    for i, key in enumerate(label_keys):
        pos = labels[:, i] == 1
        m = {}
        if pos.any() and (~pos).any():
            m["auc_vs_rest"] = float(roc_auc_score(labels[:, i], scores[:, i]))
        mask = pos | pool_only
        if pos.any() and pool_only.any():
            m["auc_vs_pool"] = float(roc_auc_score(labels[mask, i], scores[mask, i]))
        out[key] = m
    return out


def train(
    variant: config.MultiLabelVariant,
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    val_split: float = config.VAL_SPLIT,
    hidden_dim: int = config.MULTILABEL_HIDDEN_DIM,
    device: str = "auto",
    seed: int = 42,
) -> dict:
    device = resolve_device(device)
    torch.manual_seed(seed)
    keys = variant.label_keys
    print(f"[INFO] variant={variant.name} labels={keys} device={device}")

    print(f"[INFO] 임베딩 로드: {[str(p) for p, _ in variant.sources]}")
    embeddings = load_embeddings(variant)
    labeled = build_multilabel_frame(embeddings, variant)
    y_all = labeled[[f"label_{k}" for k in keys]].to_numpy()
    n_pool_only = int((y_all.sum(axis=1) == 0).sum())
    print(f"[INFO] 학습 대상: {len(labeled)}명 (pool에만 있음={n_pool_only}, embed_dim={variant.embed_dim})")
    for i, lb in enumerate(variant.labels):
        print(f"  - {lb.key}({lb.description}): 양성 {int(y_all[:, i].sum())}명")
    n_multi = int((y_all.sum(axis=1) >= 2).sum())
    print(f"  - 2개 이상 라벨 동시 보유: {n_multi}명")

    dataset = MultiLabelDataset(labeled, variant.embed_cols, keys)
    n = len(dataset)
    perm = np.random.default_rng(seed).permutation(n)
    n_val = int(n * val_split)
    val_idx, train_idx = perm[:n_val], perm[n_val:]

    train_y = y_all[train_idx]
    n_pos = train_y.sum(axis=0)
    if (n_pos == 0).any():
        empty = [k for k, c in zip(keys, n_pos) if c == 0]
        raise ValueError(f"양성이 0명인 라벨이 있습니다: {empty} — seed CSV/임베딩 인코딩을 확인할 것")
    pos_weight = (len(train_idx) - n_pos) / n_pos
    print(f"[INFO] pos_weight: {dict(zip(keys, np.round(pos_weight, 2).tolist()))}")

    train_loader = DataLoader(Subset(dataset, train_idx), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(Subset(dataset, val_idx), batch_size=batch_size, shuffle=False)

    model = MultiHeadLookalikeClassifier(variant.embed_dim, hidden_dim, len(keys), config.DROPOUT).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight, dtype=torch.float32, device=device))

    best = {"score": -1.0, "epoch": None, "state": None, "metrics": None}
    for epoch in range(1, num_epochs + 1):
        model.train()
        total_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * x.shape[0]
        train_loss = total_loss / len(train_idx)

        model.eval()
        val_scores, val_labels = [], []
        with torch.no_grad():
            for x, y in val_loader:
                val_scores.append(torch.sigmoid(model(x.to(device))).cpu().numpy())
                val_labels.append(y.numpy())
        metrics = _val_metrics(np.concatenate(val_scores), np.concatenate(val_labels), keys)
        mean_vs_pool = float(np.mean([m.get("auc_vs_pool", np.nan) for m in metrics.values()]))
        detail = " ".join(
            f"{k}={m.get('auc_vs_pool', float('nan')):.3f}/{m.get('auc_vs_rest', float('nan')):.3f}"
            for k, m in metrics.items()
        )
        print(f"[epoch {epoch}/{num_epochs}] train_loss={train_loss:.4f} "
              f"mean_auc_vs_pool={mean_vs_pool:.4f} (vs_pool/vs_rest) {detail}")

        if mean_vs_pool > best["score"]:
            best = {"score": mean_vs_pool, "epoch": epoch,
                    "state": copy.deepcopy(model.state_dict()), "metrics": metrics}

    variant.artifact_dir.mkdir(parents=True, exist_ok=True)
    torch.save(best["state"], variant.model_path)
    meta = {
        "variant": variant.name,
        "labels": [{"key": lb.key, "description": lb.description, "seed_ids_csv": str(lb.seed_ids_csv)}
                   for lb in variant.labels],
        "hidden_dim": hidden_dim,
        "embed_cols": variant.embed_cols,
        "n_train": int(len(train_idx)),
        "n_val": int(n_val),
        "n_pool_only": n_pool_only,
        "n_positive": {k: int(y_all[:, i].sum()) for i, k in enumerate(keys)},
        "pos_weight": dict(zip(keys, pos_weight.tolist())),
        "best_epoch": best["epoch"],
        "best_mean_auc_vs_pool": best["score"],
        "val_metrics": best["metrics"],
    }
    variant.labels_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] 모델 저장(best epoch={best['epoch']}, mean_auc_vs_pool={best['score']:.4f}): {variant.model_path}")
    print(f"[INFO] 라벨/검증 메타데이터: {variant.labels_path}")
    return meta


def main():
    parser = argparse.ArgumentParser(description="segment 임베딩 기반 멀티라벨(멀티헤드) lookalike 분류기 학습")
    parser.add_argument("--variant", choices=list(config.MULTILABEL_VARIANTS), required=True)
    parser.add_argument("--epochs", type=int, default=config.NUM_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=config.LEARNING_RATE)
    parser.add_argument("--val-split", type=float, default=config.VAL_SPLIT)
    parser.add_argument("--hidden-dim", type=int, default=config.MULTILABEL_HIDDEN_DIM)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()

    train(config.MULTILABEL_VARIANTS[args.variant], num_epochs=args.epochs, batch_size=args.batch_size,
          lr=args.lr, val_split=args.val_split, hidden_dim=args.hidden_dim, device=args.device)


if __name__ == "__main__":
    main()
