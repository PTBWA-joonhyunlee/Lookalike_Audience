# lookalike/scoring/train_lookalike.py
#
# segment 임베딩으로 seed=1/pool=0 지도학습 분류기를 학습한다(Variant는 파이프라인이 만든다).
#
# 클래스 불균형(seed가 pool 대비 극단적으로 작음) 처리 방식 3가지(imbalance):
#   - "sampler":     클래스 빈도 역수 가중치의 복원추출(기존 방식). seed가 작으면 양성 한 명을 에폭마다
#                    수백 번 반복해서 보게 돼 seed를 외우는 과적합이 난다(je 2026-10-02: epoch 1 이후
#                    val AUC 하락).
#   - "posweight":   pool 전체를 셔플로 한 번씩 보되 BCE에 pos_weight=n_neg/n_pos를 준다(양성 반복 없음).
#   - "undersample": 에폭마다 양성 전부 + 음성 neg_per_pos배를 비복원으로 새로 뽑는다(pos_weight=neg_per_pos).
# 검증 AUC가 patience 에폭 동안 안 오르면 중단하고, 저장하는 모델은 마지막 에폭이 아니라 검증 AUC
# 최고 에폭의 모델이다. 비교 결과는 eda/docs/classifier_imbalance_comparison.md 참고.

import copy
from typing import Optional

import numpy as np
import torch
from sklearn.metrics import roc_auc_score

from embedding.common.device import resolve_device
from . import config
from .dataset import build_labeled_frame, load_embeddings
from .model import LookalikeClassifier

IMBALANCE_MODES = ("sampler", "posweight", "undersample")


def _epoch_indices(mode: str, train_idx: np.ndarray, train_y: np.ndarray, rng: np.random.Generator,
                   neg_per_pos: int) -> np.ndarray:
    pos_idx, neg_idx = train_idx[train_y == 1], train_idx[train_y == 0]
    if mode == "sampler":
        class_counts = np.array([len(neg_idx), len(pos_idx)], dtype=np.float64)
        w = 1.0 / class_counts[train_y.astype(int)]
        return rng.choice(train_idx, size=len(train_idx), replace=True, p=w / w.sum())
    if mode == "posweight":
        return rng.permutation(train_idx)
    if mode == "undersample":
        n_neg = min(len(neg_idx), neg_per_pos * len(pos_idx))
        return rng.permutation(np.concatenate([pos_idx, rng.choice(neg_idx, size=n_neg, replace=False)]))
    raise ValueError(f"imbalance는 {IMBALANCE_MODES} 중 하나여야 합니다: {mode!r}")


def _predict(model, x: torch.Tensor, idx: np.ndarray, device, batch_size: int = 65536) -> np.ndarray:
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(idx), batch_size):
            out.append(torch.sigmoid(model(x[idx[i:i + batch_size]].to(device))).cpu().numpy())
    return np.concatenate(out)


def fit(
    x: np.ndarray,
    y: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    imbalance: str = "posweight",
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    weight_decay: float = 0.0,
    patience: int = 5,
    neg_per_pos: int = 20,
    device="cpu",
    seed: int = 42,
    test_idx: Optional[np.ndarray] = None,
    verbose: bool = True,
) -> dict:
    """x(N, D) float32, y(N,) 0/1. 검증 AUC 최고 에폭의 state_dict를 돌려준다. test_idx를 주면 그
    에폭 모델의 test AUC도 계산한다(에폭 선택에 안 쓴 데이터라 비교용으로 더 공정하다)."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    x_t = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
    y_t = torch.from_numpy(np.ascontiguousarray(y, dtype=np.float32))
    train_y = y[train_idx]
    n_pos, n_neg = int((train_y == 1).sum()), int((train_y == 0).sum())

    pos_weight = {"sampler": 1.0, "posweight": n_neg / max(n_pos, 1), "undersample": float(neg_per_pos)}[imbalance]
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight, device=device))
    model = LookalikeClassifier(x.shape[1], config.HIDDEN_DIM, config.DROPOUT).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    best = {"val_auc": -1.0, "epoch": 0, "state": None}
    history, stale = [], 0
    for epoch in range(1, num_epochs + 1):
        idx = _epoch_indices(imbalance, train_idx, train_y, rng, neg_per_pos)
        model.train()
        total_loss = 0.0
        for i in range(0, len(idx), batch_size):
            b = idx[i:i + batch_size]
            xb, yb = x_t[b].to(device), y_t[b].to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(b)
        val_auc = roc_auc_score(y[val_idx], _predict(model, x_t, val_idx, device))
        history.append({"epoch": epoch, "train_loss": total_loss / len(idx), "val_auc": float(val_auc)})
        if verbose:
            print(f"[epoch {epoch}/{num_epochs}] train_loss={total_loss / len(idx):.4f} val_auc={val_auc:.4f}")
        if val_auc > best["val_auc"]:
            best.update(val_auc=float(val_auc), epoch=epoch, state=copy.deepcopy(model.state_dict()))
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                if verbose:
                    print(f"[INFO] early stop: {patience} 에폭 동안 val AUC 개선 없음(best epoch {best['epoch']})")
                break

    result = {"best_epoch": best["epoch"], "best_val_auc": best["val_auc"], "history": history,
              "state_dict": best["state"], "imbalance": imbalance, "n_pos_train": n_pos, "n_neg_train": n_neg}
    if test_idx is not None:
        result["test_auc_last"] = float(roc_auc_score(y[test_idx], _predict(model, x_t, test_idx, device)))
        model.load_state_dict(best["state"])
        result["test_auc"] = float(roc_auc_score(y[test_idx], _predict(model, x_t, test_idx, device)))
    return result


def train(
    variant: config.Variant,
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    val_split: float = config.VAL_SPLIT,
    device: str = "auto",
    seed: int = 42,
    embeddings=None,
    imbalance: str = "posweight",
    patience: int = 5,
    weight_decay: float = 0.0,
) -> dict:
    """학습 설정 + 결과(best epoch, history 등)를 dict로 돌려준다 — 호출부가 config.json으로 저장한다.
    embeddings(DataFrame: device_ifa + embed_cols)를 직접 주면 variant.sources CSV를 읽지 않는다 —
    seed/pool 임베딩이 서로 다른 파일에 있는 새 파이프라인(run_seed_scenario1.py)용."""
    device = resolve_device(device)
    print(f"[INFO] variant={variant.name} device={device} imbalance={imbalance}")

    if embeddings is None:
        print(f"[INFO] 임베딩 로드: {[str(p) for p, _ in variant.sources]}")
        embeddings = load_embeddings(variant)
    labeled = build_labeled_frame(embeddings, variant)
    y = labeled["label"].to_numpy(dtype=np.float32)
    x = labeled[variant.embed_cols].to_numpy(dtype=np.float32)
    print(f"[INFO] 학습 대상: {len(labeled)}명 (seed={int(y.sum())}, pool={int((y == 0).sum())}, embed_dim={variant.embed_dim})")

    perm = np.random.default_rng(seed).permutation(len(labeled))
    n_val = int(len(labeled) * val_split)
    val_idx, train_idx = perm[:n_val], perm[n_val:]

    res = fit(x, y, train_idx, val_idx, imbalance=imbalance, num_epochs=num_epochs, batch_size=batch_size,
              lr=lr, weight_decay=weight_decay, patience=patience, device=device, seed=seed)
    print(f"[INFO] best epoch {res['best_epoch']} (val_auc={res['best_val_auc']:.4f}) 모델을 저장")

    variant.artifact_dir.mkdir(parents=True, exist_ok=True)
    torch.save(res["state_dict"], variant.model_path)
    print(f"[INFO] 모델 저장: {variant.model_path}")
    return {
        "imbalance": imbalance, "num_epochs": num_epochs, "batch_size": batch_size, "learning_rate": lr,
        "weight_decay": weight_decay, "patience": patience, "val_split": val_split, "split_seed": seed,
        "hidden_dim": config.HIDDEN_DIM, "dropout": config.DROPOUT, "embed_dim": variant.embed_dim,
        "device": str(device), "n_seed": int(y.sum()), "n_pool": int((y == 0).sum()),
        "n_train": int(len(train_idx)), "n_val": int(n_val),
        "best_epoch": res["best_epoch"], "best_val_auc": res["best_val_auc"],
        "epochs_run": len(res["history"]), "history": res["history"],
    }
