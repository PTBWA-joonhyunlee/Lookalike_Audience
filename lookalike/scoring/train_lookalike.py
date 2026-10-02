# lookalike/scoring/train_lookalike.py
#
# segment 임베딩으로 seed=1/pool=0 지도학습 분류기를 학습한다(Variant는 파이프라인이 만든다).
#
# 2026-08-19(je variant 추가로 WeightedRandomSampler 도입): 피엘라벤은 seed/pool 규모가
# 비슷해서(약 250만 vs 255만) 원래 단순 셔플로 충분했지만, je(1,922명)처럼 seed가 pool
# 대비 극단적으로 작은 경우 균등 셔플로는 배치당 양성 표본이 거의 안 걸려 학습이 붕괴한다.
# 클래스 빈도 역수 가중치의 WeightedRandomSampler로 학습 배치를 뽑도록 바꿨다 — seed/pool
# 규모가 비슷한 경우엔 가중치가 거의 균일해져 기존 동작과 사실상 같다.

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Subset, WeightedRandomSampler

from embedding.common.device import resolve_device
from . import config
from .dataset import EmbeddingLabelDataset, build_labeled_frame, load_embeddings
from .model import LookalikeClassifier


def train(
    variant: config.Variant,
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    val_split: float = config.VAL_SPLIT,
    device: str = "auto",
    seed: int = 42,
    embeddings=None,
) -> None:
    """embeddings(DataFrame: device_ifa + embed_cols)를 직접 주면 variant.sources CSV를 읽지 않는다 —
    seed/pool 임베딩이 서로 다른 파일에 있는 새 파이프라인(run_seed_scenario1.py)용."""
    device = resolve_device(device)
    print(f"[INFO] variant={variant.name} device={device}")

    print(f"[INFO] 임베딩 로드: {[str(p) for p, _ in variant.sources]}")
    if embeddings is None:
        embeddings = load_embeddings(variant)
    labeled = build_labeled_frame(embeddings, variant)
    n_pos = int(labeled["label"].sum())
    n_neg = len(labeled) - n_pos
    print(f"[INFO] 학습 대상: {len(labeled)}명 (seed={n_pos}, pool={n_neg}, embed_dim={variant.embed_dim})")

    dataset = EmbeddingLabelDataset(labeled, variant.embed_cols)
    n = len(dataset)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    n_val = int(n * val_split)
    val_idx, train_idx = perm[:n_val], perm[n_val:]

    # seed:pool 비율이 극단적으로 기울면(예: je 1,922 vs pool 250만, 약 1:1300) 균등 셔플로는
    # 배치 하나에 양성이 평균 1개도 안 걸려 학습이 사실상 "전부 pool" 쪽으로 붕괴한다 —
    # 클래스별 빈도의 역수를 샘플 가중치로 준 WeightedRandomSampler(복원추출)로 각 배치에
    # 양성/음성이 고르게 섞이도록 한다. seed:pool 규모가 비슷한 경우(피엘라벤)에도 가중치가
    # 거의 균일해져 기존 동작과 사실상 같다.
    train_labels = labeled["label"].to_numpy()[train_idx]
    class_counts = np.bincount(train_labels.astype(int), minlength=2)
    sample_weights = 1.0 / class_counts[train_labels.astype(int)]
    sampler = WeightedRandomSampler(sample_weights, num_samples=len(train_idx), replacement=True)

    train_loader = DataLoader(Subset(dataset, train_idx), batch_size=batch_size, sampler=sampler)
    val_loader = DataLoader(Subset(dataset, val_idx), batch_size=batch_size, shuffle=False)

    model = LookalikeClassifier(variant.embed_dim, config.HIDDEN_DIM, config.DROPOUT).to(device)
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

    variant.artifact_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), variant.model_path)
    print(f"[INFO] 모델 저장: {variant.model_path}")
