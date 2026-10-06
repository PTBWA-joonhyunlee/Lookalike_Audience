# lookalike/scoring/multilabel.py
#
# 멀티라벨 lookalike 분류기 — seed가 여러 개일 때 seed 하나당 라벨 하나(독립 sigmoid 헤드)를 두고 공유
# trunk 하나로 한 번에 학습한다(model.MultiHeadLookalikeClassifier). 한 유저가 여러 seed에 동시에 속할 수
# 있고(라벨 행렬의 한 행에 1이 여러 개), pool은 모든 라벨이 0이다. 라벨별 불균형은 라벨마다
# pos_weight = n_neg/n_pos로 처리한다(단일 라벨 posweight 모드와 같은 방식 — classifier_imbalance_comparison.md).
# 스코어는 seed별 점수 열이고, "seed별 상위 N%" 선택/합집합은 호출부(pipeline)가 한다.

import copy
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import roc_auc_score

from embedding.common.device import resolve_device
from . import config
from .model import MultiHeadLookalikeClassifier

ID_COL = config.ID_COL


def stratified_split(Y: np.ndarray, val_split: float, seed: int):
    """라벨 조합(예: seed1만/seed2만/둘 다/없음)별로 같은 비율을 val로 뗀다 — seed가 작아도 val에 양성이 남는다."""
    codes = (Y.astype(np.int64) * (1 << np.arange(Y.shape[1]))).sum(axis=1)
    rng = np.random.default_rng(seed)
    val = []
    for c in np.unique(codes):
        idx = rng.permutation(np.flatnonzero(codes == c))
        val.append(idx[:int(round(len(idx) * val_split))])
    val_idx = np.sort(np.concatenate(val))
    mask = np.ones(len(Y), dtype=bool)
    mask[val_idx] = False
    return np.flatnonzero(mask), val_idx


def _predict(model, x: torch.Tensor, idx: np.ndarray, device, batch_size: int = 65536) -> np.ndarray:
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(idx), batch_size):
            out.append(torch.sigmoid(model(x[idx[i:i + batch_size]].to(device))).cpu().numpy())
    return np.concatenate(out)


def _label_aucs(Y: np.ndarray, P: np.ndarray) -> List[Optional[float]]:
    aucs = []
    for k in range(Y.shape[1]):
        aucs.append(float(roc_auc_score(Y[:, k], P[:, k])) if 0 < Y[:, k].sum() < len(Y) else None)
    return aucs


def train_multilabel(
    x: np.ndarray,
    Y: np.ndarray,
    labels: Sequence[str],
    model_path,
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    val_split: float = config.VAL_SPLIT,
    weight_decay: float = 0.0,
    patience: int = 5,
    device: str = "auto",
    seed: int = 42,
) -> dict:
    """x(N,D) float32, Y(N,K) 0/1. 검증 평균 AUC가 최고인 에폭의 가중치를 model_path에 저장하고 학습 결과 dict를 돌려준다."""
    device = resolve_device(device)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    K = Y.shape[1]
    train_idx, val_idx = stratified_split(Y, val_split, seed)
    n_pos = Y[train_idx].sum(axis=0)
    n_neg = len(train_idx) - n_pos
    pos_weight = n_neg / np.maximum(n_pos, 1)
    print(f"[INFO] multilabel device={device} labels={list(labels)} train={len(train_idx):,} val={len(val_idx):,} "
          f"양성(train)={n_pos.astype(int).tolist()} pos_weight={np.round(pos_weight, 1).tolist()}")

    x_t = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
    Y_t = torch.from_numpy(np.ascontiguousarray(Y, dtype=np.float32))
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight, dtype=torch.float32, device=device))
    model = MultiHeadLookalikeClassifier(x.shape[1], config.HIDDEN_DIM, K, config.DROPOUT).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    best = {"val_auc": -1.0, "epoch": 0, "state": None, "label_aucs": None}
    history, stale = [], 0
    for epoch in range(1, num_epochs + 1):
        idx = rng.permutation(train_idx)
        model.train()
        total = 0.0
        for i in range(0, len(idx), batch_size):
            b = idx[i:i + batch_size]
            xb, yb = x_t[b].to(device), Y_t[b].to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            total += loss.item() * len(b)
        aucs = _label_aucs(Y[val_idx], _predict(model, x_t, val_idx, device))
        valid = [a for a in aucs if a is not None]
        mean_auc = float(np.mean(valid)) if valid else float("nan")
        history.append({"epoch": epoch, "train_loss": total / len(idx), "val_auc_mean": mean_auc, "val_auc": aucs})
        print(f"[epoch {epoch}/{num_epochs}] train_loss={total / len(idx):.4f} val_auc_mean={mean_auc:.4f} "
              f"per_label={[None if a is None else round(a, 4) for a in aucs]}")
        if mean_auc > best["val_auc"]:
            best.update(val_auc=mean_auc, epoch=epoch, state=copy.deepcopy(model.state_dict()), label_aucs=aucs)
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                print(f"[INFO] early stop: {patience} 에폭 동안 val 평균 AUC 개선 없음(best epoch {best['epoch']})")
                break

    torch.save({"state_dict": best["state"], "labels": list(labels), "input_dim": int(x.shape[1]),
                "hidden_dim": config.HIDDEN_DIM, "dropout": config.DROPOUT}, model_path)
    print(f"[INFO] best epoch {best['epoch']} (val_auc_mean={best['val_auc']:.4f}) 모델 저장: {model_path}")
    return {
        "mode": "multilabel", "labels": list(labels), "num_epochs": num_epochs, "batch_size": batch_size,
        "learning_rate": lr, "weight_decay": weight_decay, "patience": patience, "val_split": val_split,
        "split_seed": seed, "split": "라벨 조합별 층화", "hidden_dim": config.HIDDEN_DIM, "dropout": config.DROPOUT,
        "embed_dim": int(x.shape[1]), "device": str(device),
        "n_train": int(len(train_idx)), "n_val": int(len(val_idx)),
        "n_pos_train": n_pos.astype(int).tolist(), "n_pos_val": Y[val_idx].sum(axis=0).astype(int).tolist(),
        "pos_weight": pos_weight.tolist(), "n_both_labels": int((Y.sum(axis=1) > 1).sum()),
        "best_epoch": best["epoch"], "best_val_auc_mean": best["val_auc"], "best_val_auc_per_label": best["label_aucs"],
        "epochs_run": len(history), "history": history,
    }


def load_multilabel(model_path, device):
    ckpt = torch.load(model_path, map_location=device)
    model = MultiHeadLookalikeClassifier(ckpt["input_dim"], ckpt["hidden_dim"], len(ckpt["labels"]), ckpt["dropout"])
    model.load_state_dict(ckpt["state_dict"])
    return model.to(device).eval(), ckpt["labels"]


def score_multilabel(model_path, embeddings_csv, candidate_ids: set, device: str = "auto",
                     chunksize: int = 500_000) -> pd.DataFrame:
    """임베딩 CSV를 청크로 읽어 candidate_ids에 속한 행만 스코어링한다. 반환: device_ifa + 라벨별 점수 열(float32).
    device_ifa 중복은 첫 행만 쓴다."""
    device = resolve_device(device)
    model, labels = load_multilabel(model_path, device)
    cols = [ID_COL, *config.SEGMENT_EMBED_COLS]
    seen, frames = set(), []
    dtypes = {ID_COL: str, **{c: "float32" for c in cols[1:]}}
    for chunk in pd.read_csv(embeddings_csv, usecols=cols, dtype=dtypes, chunksize=chunksize):
        chunk = chunk[chunk[ID_COL].isin(candidate_ids)]
        chunk = chunk[~chunk[ID_COL].isin(seen)].drop_duplicates(subset=[ID_COL])
        if chunk.empty:
            continue
        seen.update(chunk[ID_COL])
        with torch.no_grad():
            p = torch.sigmoid(model(torch.from_numpy(chunk[cols[1:]].to_numpy(dtype=np.float32)).to(device))).cpu().numpy()
        out = pd.DataFrame(p.astype(np.float32), columns=[f"score_{l}" for l in labels])
        out.insert(0, ID_COL, chunk[ID_COL].to_numpy())
        frames.append(out)
    return pd.concat(frames, ignore_index=True)


# ---------- seed별 상위 N% 선택 / 합집합 / 교집합 ----------

def top_masks(scores: np.ndarray, pct: float) -> np.ndarray:
    """(N,K) 점수에서 seed(열)별 상위 pct%를 True로 하는 (N,K) bool. 열마다 정확히 round(N*pct/100)개
    (동점은 argsort 순서로 끊는다)."""
    n = scores.shape[0]
    m = max(int(round(n * pct / 100.0)), 0)
    mask = np.zeros(scores.shape, dtype=bool)
    if m:
        for k in range(scores.shape[1]):
            mask[np.argpartition(-scores[:, k], m - 1)[:m], k] = True
    return mask


def find_pct_for_union(scores: np.ndarray, target_union: int, lo: float = 0.01, hi: float = 100.0,
                       tol: float = 0.001) -> float:
    """모든 seed에 같은 상위 pct%를 줬을 때 합집합 크기가 target_union에 가장 가까워지는 pct(이분 탐색, 합집합은 pct에 단조 증가)."""
    def union_size(p):
        return int(top_masks(scores, p).any(axis=1).sum())

    while hi - lo > tol:
        mid = (lo + hi) / 2
        if union_size(mid) < target_union:
            lo = mid
        else:
            hi = mid
    a, b = lo, hi
    return a if abs(union_size(a) - target_union) <= abs(union_size(b) - target_union) else b
