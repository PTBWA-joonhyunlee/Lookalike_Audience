# seed/train/segment_features.py
#
# segment_features Autoencoder를 학습하고 model.pt를 저장한다. 임베딩 추출은 하지 않는다.
# 실행 전에 반드시 `python -m embedding.segment_features.build_features`로
# segment_features.npz/segment_bert_lookup.npz/age_bracket_vocab.json을 먼저 만들어야 한다 —
# 이 스크립트는 그 결과를 읽기만 하고, BERT 인코딩(무거운 부분)은 다시 하지 않는다.
#
# 실행(저장소 루트가 아니라 seed/ 안에서 cd 후 실행):
#   cd seed && ..\.venv\Scripts\python.exe -m train.segment_features [--input <npz>] [--output <저장 경로>] [--config <json>]
# 입력: --input 생략 시 embedding/segment_features/config.ARTIFACT_DIR/segment_features.npz
# 출력: --output 생략 시 같은 디렉터리에 model.pt

import argparse
import logging
import os
from typing import Optional

import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from embedding.common.device import resolve_device
from embedding.common.train_config import load_train_config
from embedding.common.vocab import CategoryVocab
from embedding.segment_features import config
from embedding.segment_features.bert_lookup import SegmentEmbeddingLookup
from embedding.segment_features.dataset import SegmentFeaturesDataset
from embedding.segment_features.model import POOLED_GROUPS, SegmentFeaturesAutoencoder

logger = logging.getLogger(__name__)


def _resolve_npz_path(input_path: Optional[str] = None) -> str:
    path = input_path or str(config.ARTIFACT_DIR / "segment_features.npz")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} 가 없습니다 — 먼저 `python -m embedding.segment_features.build_features`를 실행하세요."
        )
    return path


def train(
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    input_path: Optional[str] = None,
    artifact_dir: Optional[str] = None,
    device: str = "auto",
) -> None:
    device = resolve_device(device)
    logger.info("device=%s", device)
    print(f"[INFO] device={device}")

    npz_path = _resolve_npz_path(input_path)
    print(f"[INFO] segment_features 소스: {npz_path}")
    dataset = SegmentFeaturesDataset(npz_path)
    loader = DataLoader(dataset, batch_size=min(batch_size, len(dataset)), shuffle=True)

    age_vocab = CategoryVocab.load(config.AGE_VOCAB_PATH)
    bert_lookup = SegmentEmbeddingLookup.load(config.BERT_LOOKUP_PATH)
    bert_lookup_vectors = torch.tensor(bert_lookup.vectors, dtype=torch.float32)

    model = SegmentFeaturesAutoencoder(
        age_vocab_size=len(age_vocab),
        bert_lookup_vectors=bert_lookup_vectors,
        age_embed_dim=config.AGE_EMBED_DIM,
        proj_dims=config.PROJ_DIMS,
        hidden_dim=config.HIDDEN_DIM,
        z_dim=config.EMBED_DIM,
        freeze_bert_lookup=config.FREEZE_BERT_LOOKUP,
    ).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    gender_criterion = torch.nn.MSELoss()
    age_criterion = torch.nn.CrossEntropyLoss()

    model.train()
    for epoch in range(1, num_epochs + 1):
        total_loss = 0.0
        for _, batch in tqdm(loader, desc=f"epoch {epoch}/{num_epochs}", leave=False, mininterval=5.0):
            batch = {k: v.to(device) for k, v in batch.items()}

            optimizer.zero_grad()
            _, gender_pred, age_logits, group_projections, group_recons = model(batch)

            loss = gender_criterion(gender_pred, batch["gender_score"])
            loss = loss + age_criterion(age_logits, batch["age_bracket_idx"])
            # 복원 타깃(인코더의 projection 출력)에 detach — 그렇지 않으면 인코더/디코더가
            # 서로를 향해 임의의 상수로 붕괴할 수 있음(model.py 상단 주석 참고).
            for g in POOLED_GROUPS:
                loss = loss + torch.nn.functional.mse_loss(group_recons[g], group_projections[g].detach())

            loss.backward()
            optimizer.step()
            total_loss += loss.item() * batch["gender_score"].shape[0]

        avg_loss = total_loss / len(dataset)
        logger.info("epoch %d/%d loss=%.6f", epoch, num_epochs, avg_loss)
        print(f"[epoch {epoch}/{num_epochs}] loss={avg_loss:.6f}")

    artifact_dir = artifact_dir or str(config.ARTIFACT_DIR)
    os.makedirs(artifact_dir, exist_ok=True)
    model_path = os.path.join(artifact_dir, "model.pt")
    torch.save(model.state_dict(), model_path)
    print(f"[INFO] 모델 저장: {model_path}")


def main():
    parser = argparse.ArgumentParser(description="segment_features Autoencoder를 학습하고 모델을 저장한다.")
    parser.add_argument("--input", help=f"segment_features.npz 경로 (생략 시 기본값: {config.ARTIFACT_DIR / 'segment_features.npz'})")
    parser.add_argument("--output", help=f"모델 저장 디렉터리 (생략 시 기본 경로: {config.ARTIFACT_DIR})")
    parser.add_argument(
        "--config",
        help="dataset_path/output_model_path/num_epochs/batch_size/learning_rate/device를 담은 JSON 설정 파일 "
        "(config/train_config.example.json 참고). --input/--output/--device를 같이 주면 그 값이 우선한다.",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        help="학습에 쓸 디바이스 (기본값: auto, cuda 사용 가능하면 cuda, 아니면 cpu)",
    )
    args = parser.parse_args()

    cfg = load_train_config(args.config) if args.config else {}
    input_path = args.input or cfg.get("dataset_path")
    artifact_dir = args.output or cfg.get("output_model_path")
    num_epochs = cfg.get("num_epochs", config.NUM_EPOCHS)
    batch_size = cfg.get("batch_size", config.BATCH_SIZE)
    lr = cfg.get("learning_rate", config.LEARNING_RATE)
    device = args.device or cfg.get("device", "auto")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=== segment_features 임베딩(Autoencoder) 학습 시작 ===")
    train(num_epochs=num_epochs, batch_size=batch_size, lr=lr, input_path=input_path, artifact_dir=artifact_dir, device=device)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
