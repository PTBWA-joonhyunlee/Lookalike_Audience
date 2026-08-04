# seed/train/media_sequence.py
#
# media_features.npz(build_features.py 출력)에 SASRec(causal 다음-아이템 예측)을 학습하고
# 아티팩트(model.pt)를 저장한다. 임베딩 추출은 하지 않는다 — inference/media_sequence.py를 쓴다.
#
# 실행 전 준비: `python -m embedding.media_sequence.build_features`로 media_features.npz +
# vocab 4종(vocab_media.json 등)을 먼저 만들어야 한다(무거운 CSV 전처리는 여기서 하지 않음).
# 실행(저장소 루트가 아니라 seed/ 안에서 cd 후 실행):
#   cd seed && ..\.venv\Scripts\python.exe -m train.media_sequence [--epochs N] [--device auto]

import argparse
import logging
import os

import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from embedding.common.device import resolve_device
from embedding.common.vocab import CategoryVocab
from embedding.media_sequence import config
from embedding.media_sequence.dataset import IGNORE_INDEX, MediaSequenceDataset
from embedding.media_sequence.model import SASRec

logger = logging.getLogger(__name__)


def _load_vocabs():
    if not os.path.exists(config.FEATURES_NPZ_PATH):
        raise FileNotFoundError(
            f"{config.FEATURES_NPZ_PATH} 가 없습니다 — 먼저 "
            "`python -m embedding.media_sequence.build_features`를 실행하세요."
        )
    return (
        CategoryVocab.load(config.MEDIA_VOCAB_PATH),
        CategoryVocab.load(config.INVENTORY_TYPE_VOCAB_PATH),
        CategoryVocab.load(config.AD_TYPE_VOCAB_PATH),
        CategoryVocab.load(config.CONNECTION_TYPE_VOCAB_PATH),
    )


def train(
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    device: str = "auto",
) -> None:
    device = resolve_device(device)
    logger.info("device=%s", device)
    print(f"[INFO] device={device}")

    media_vocab, inventory_vocab, ad_type_vocab, connection_type_vocab = _load_vocabs()

    dataset = MediaSequenceDataset(config.FEATURES_NPZ_PATH, max_len=config.MAX_SEQ_LEN, min_len=config.MIN_SEQ_LEN)
    if dataset.skipped:
        msg = (
            f"시퀀스 길이 {config.MIN_SEQ_LEN} 미만이라 학습에서 제외된 디바이스 "
            f"{dataset.skipped:,}개 (inference에서는 포함되어 뽑힘)"
        )
        logger.warning(msg)
        print(f"[WARN] {msg}")
    if len(dataset) == 0:
        raise ValueError(f"다음-아이템 학습에 쓸 수 있는(시퀀스 길이 {config.MIN_SEQ_LEN} 이상) 디바이스가 없습니다.")
    print(f"[INFO] 학습 대상 디바이스: {len(dataset):,}개")

    loader = DataLoader(dataset, batch_size=min(batch_size, len(dataset)), shuffle=True)

    model = SASRec(
        vocab_size=len(media_vocab),
        max_len=config.MAX_SEQ_LEN,
        embed_dim=config.EMBED_DIM,
        n_heads=config.N_HEADS,
        n_layers=config.N_LAYERS,
        ffn_dim=config.FFN_DIM,
        dropout=config.DROPOUT,
        inventory_type_vocab_size=len(inventory_vocab),
        ad_type_vocab_size=len(ad_type_vocab),
        connection_type_vocab_size=len(connection_type_vocab),
        time_gap_vocab_size=config.TIME_GAP_VOCAB_SIZE,
        time_of_day_vocab_size=config.TIME_OF_DAY_VOCAB_SIZE,
    ).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = torch.nn.CrossEntropyLoss(ignore_index=IGNORE_INDEX)

    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    best_loss = float("inf")

    model.train()
    for epoch in range(1, num_epochs + 1):
        total_loss = 0.0
        total_tokens = 0
        for _, input_ids, target_ids, _lengths, inv_ids, ad_ids, conn_ids, gap_ids, tod_ids in tqdm(
            loader, desc=f"epoch {epoch}/{num_epochs}", leave=False, mininterval=5.0
        ):
            input_ids = input_ids.to(device)
            target_ids = target_ids.to(device)
            inv_ids = inv_ids.to(device)
            ad_ids = ad_ids.to(device)
            conn_ids = conn_ids.to(device)
            gap_ids = gap_ids.to(device)
            tod_ids = tod_ids.to(device)

            optimizer.zero_grad()
            logits = model(input_ids, inv_ids, ad_ids, conn_ids, gap_ids, tod_ids)  # (B, L, V)
            loss = criterion(logits.reshape(-1, logits.size(-1)), target_ids.reshape(-1))

            loss.backward()
            optimizer.step()

            n_valid = (target_ids != IGNORE_INDEX).sum().item()
            total_loss += loss.item() * n_valid
            total_tokens += n_valid

        avg_loss = total_loss / max(total_tokens, 1)
        logger.info("epoch %d/%d loss=%.4f", epoch, num_epochs, avg_loss)
        print(f"[epoch {epoch}/{num_epochs}] loss={avg_loss:.4f}")

        # segment_features 학습 때 마지막 epoch이 중간 epoch보다 나빠졌는데도 되돌릴 방법이
        # 없었던 문제를 겪지 않도록, epoch마다
        # 마지막 상태(model.pt)와 별개로 loss가 가장 낮았던 시점(model_best.pt)도 남긴다.
        torch.save(model.state_dict(), config.MODEL_PATH)
        if avg_loss < best_loss:
            best_loss = avg_loss
            torch.save(model.state_dict(), config.ARTIFACT_DIR / "model_best.pt")

    print(f"[INFO] 모델 저장(마지막 epoch): {config.MODEL_PATH}")
    print(f"[INFO] 모델 저장(최저 loss={best_loss:.4f}): {config.ARTIFACT_DIR / 'model_best.pt'}")


def main():
    parser = argparse.ArgumentParser(description="media_features.npz 시퀀스에 SASRec을 학습하고 모델을 저장한다.")
    parser.add_argument("--epochs", type=int, default=config.NUM_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=config.LEARNING_RATE)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=== media_sequence 임베딩(SASRec) 학습 시작 ===")
    train(num_epochs=args.epochs, batch_size=args.batch_size, lr=args.lr, device=args.device)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
