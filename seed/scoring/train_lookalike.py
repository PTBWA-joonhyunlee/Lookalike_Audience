# seed/scoring/train_lookalike.py
#
# segment 임베딩(32dim)만으로 seed=1/pool=0 지도학습 분류기를 학습한다. addi 트랙의
# scoring/train_supervised_lookalike.py에 해당하는 자리 — 다만 이번엔 seed/pool 규모가
# 비슷해서(약 250만 vs 255만, addi처럼 양성이 0.01% 수준으로 희소하지 않음) 층화
# 미니배치 샘플링이나 pos_weight 없이 단순 셔플 + train/val 분할로 충분하다.
#
# 실행 전 준비: inference.segment_features로 임베딩 CSV를 먼저 만들어야 한다.
# 실행(seed/ 안에서 cd 후): ..\.venv\Scripts\python.exe -m scoring.train_lookalike

import argparse

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Subset

from embedding.common.device import resolve_device
from . import config
from .dataset import EmbeddingLabelDataset, build_labeled_frame, load_embeddings
from .model import LookalikeClassifier


def train(
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    val_split: float = config.VAL_SPLIT,
    device: str = "auto",
    seed: int = 42,
) -> None:
    device = resolve_device(device)
    print(f"[INFO] device={device}")

    print(f"[INFO] 임베딩 로드: {config.EMBEDDINGS_CSV}")
    embeddings = load_embeddings()
    labeled = build_labeled_frame(embeddings)
    n_pos = int(labeled["label"].sum())
    n_neg = len(labeled) - n_pos
    print(f"[INFO] 학습 대상: {len(labeled)}명 (seed={n_pos}, pool={n_neg})")

    dataset = EmbeddingLabelDataset(labeled)
    n = len(dataset)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    n_val = int(n * val_split)
    val_idx, train_idx = perm[:n_val], perm[n_val:]

    train_loader = DataLoader(Subset(dataset, train_idx), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(Subset(dataset, val_idx), batch_size=batch_size, shuffle=False)

    model = LookalikeClassifier(config.EMBED_DIM, config.HIDDEN_DIM, config.DROPOUT).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = torch.nn.BCEWithLogitsLoss()

    for epoch in range(1, num_epochs + 1):
        model.train()
        total_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * x.shape[0]
        train_loss = total_loss / len(train_idx)

        model.eval()
        val_scores, val_labels = [], []
        with torch.no_grad():
            for x, y in val_loader:
                logits = model(x.to(device))
                val_scores.append(torch.sigmoid(logits).cpu().numpy())
                val_labels.append(y.numpy())
        val_scores = np.concatenate(val_scores)
        val_labels = np.concatenate(val_labels)
        val_auc = roc_auc_score(val_labels, val_scores)
        print(f"[epoch {epoch}/{num_epochs}] train_loss={train_loss:.4f} val_auc={val_auc:.4f}")

    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), config.MODEL_PATH)
    print(f"[INFO] 모델 저장: {config.MODEL_PATH}")


def main():
    parser = argparse.ArgumentParser(description="segment 임베딩 기반 lookalike 분류기 학습")
    parser.add_argument("--epochs", type=int, default=config.NUM_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=config.LEARNING_RATE)
    parser.add_argument("--val-split", type=float, default=config.VAL_SPLIT)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()

    train(num_epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
          val_split=args.val_split, device=args.device)


if __name__ == "__main__":
    main()
