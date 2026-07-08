# train/media_sequence.py
#
# top500_media_visit 이벤트에 SASRec(causal 다음-아이템 예측)을 학습하고 아티팩트(model.pt,
# vocab_media.json 등)를 저장한다. 임베딩 추출은 하지 않는다 — 학습된 모델로 임베딩을 뽑으려면
# inference/media_sequence.py를 쓴다.
# 실행: .venv\Scripts\python.exe -m train.media_sequence [--input <csv>] [--output <모델 저장 경로>] [--config <json>]
# 입력: --input 생략 시 data/top500*.csv 중 최신 파일 자동 선택 (01_top500_media_visit.sql 결과)
#       — 이벤트 그레인이며 "단기간 재방문 필터링"(30분 세션 규칙)은 이미 01.sql에서 끝난 상태.
#       req_user_id로 묶어 ts 순서대로 나열하면 그대로 시퀀스가 된다 (dataset.build_sequences).
# 출력: --output 생략 시 data/models/media_sequence/  (model.pt, vocab_media.json 등 —
#       inference/media_sequence.py가 재사용)
# --config: dataset_path/output_model_path/num_epochs/batch_size/learning_rate를 담은 JSON
#       (config/train_config.example.json 참고). --input/--output을 같이 주면 그 값이 config보다
#       우선한다. num_epochs/batch_size/learning_rate는 config에만 있으면 적용되고, 없으면
#       embedding/media_sequence/config.py의 기본값을 쓴다.
#
# 모델/데이터셋/전처리 정의(embedding/media_sequence/)는 이 학습 루프와 inference/media_sequence.py가
# 공유하는 자원이라 이 폴더로 옮기지 않았다 — 자세한 구조는 embedding/media_sequence/, README.md 참고.

import argparse
import logging
import os
from typing import Optional

import pandas as pd
import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from embedding.common.io import latest_file
from embedding.common.train_config import load_train_config
from embedding.common.vocab import CategoryVocab
from embedding.media_sequence import config
from embedding.media_sequence.dataset import IGNORE_INDEX, MediaSequenceDataset
from embedding.media_sequence.model import SASRec
from embedding.media_sequence.side_features import SideFeatureVocabs

logger = logging.getLogger(__name__)


def _load_source(input_path: Optional[str] = None) -> pd.DataFrame:
    if input_path:
        path = input_path
        if not os.path.exists(path):
            raise FileNotFoundError(f"입력 CSV를 찾을 수 없습니다: {path}")
    else:
        pattern = os.path.join(str(config.DATA_DIR), config.DATA_GLOB)
        path = latest_file(pattern)
        if path is None:
            raise FileNotFoundError(f"{config.DATA_DIR} 에 '{config.DATA_GLOB}' 패턴의 CSV가 없습니다.")
    logger.info("media_sequence 소스: %s", path)
    print(f"[INFO] media_sequence 소스: {path}")

    df = pd.read_csv(path)

    required = [
        config.ID_COL,
        config.MEDIA_COL,
        config.TS_COL,
        config.CONTENT_GENRE_COL,
        config.AD_TYPE_COL,
        config.CONNECTION_TYPE_COL,
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"소스 CSV에 누락된 컬럼: {missing}")

    # 이벤트 그레인 데이터라 req_user_id가 여러 행에 걸쳐 반복되는 게 정상이다
    # (user_profile처럼 유저 1행을 보장하는 소스가 아님 — 여기서 dedup하면 안 됨).
    return df


def _fit_vocab(df: pd.DataFrame) -> CategoryVocab:
    vocab = CategoryVocab.build(
        df[config.MEDIA_COL].dropna(), min_freq=config.MIN_FREQ, max_size=config.MAX_VOCAB_SIZE
    )
    logger.info("media vocab size=%d (이벤트 수=%d)", len(vocab), len(df))
    return vocab


def _save_artifacts(
    model: SASRec, vocab: CategoryVocab, side_vocabs: SideFeatureVocabs, artifact_dir: Optional[str] = None
) -> None:
    artifact_dir = artifact_dir or config.ARTIFACT_DIR
    os.makedirs(artifact_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(str(artifact_dir), "model.pt"))
    vocab.save(os.path.join(str(artifact_dir), "vocab_media.json"))
    side_vocabs.save(artifact_dir)
    print(f"[INFO] 모델/vocab 저장: {artifact_dir}")


def train(
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    input_path: Optional[str] = None,
    artifact_dir: Optional[str] = None,
) -> None:
    df = _load_source(input_path)
    vocab = _fit_vocab(df)
    side_vocabs = SideFeatureVocabs.fit(df)
    logger.info(
        "side vocab sizes: genre=%d ad_type=%d connection_type=%d",
        len(side_vocabs.genre),
        len(side_vocabs.ad_type),
        len(side_vocabs.connection_type),
    )

    dataset_kwargs = dict(
        id_col=config.ID_COL,
        media_col=config.MEDIA_COL,
        ts_col=config.TS_COL,
        genre_col=config.CONTENT_GENRE_COL,
        ad_type_col=config.AD_TYPE_COL,
        connection_type_col=config.CONNECTION_TYPE_COL,
        side_vocabs=side_vocabs,
        max_genres=config.MAX_GENRES_PER_EVENT,
    )

    train_dataset = MediaSequenceDataset(
        df, vocab, config.MAX_SEQ_LEN, **dataset_kwargs, min_len=config.MIN_SEQ_LEN
    )
    if train_dataset.skipped:
        msg = (
            f"시퀀스 길이 {config.MIN_SEQ_LEN} 미만이라 학습에서 제외된 유저 "
            f"{train_dataset.skipped}명 (inference에서는 포함되어 뽑힘)"
        )
        logger.warning(msg)
        print(f"[WARN] {msg}")
    if len(train_dataset) == 0:
        raise ValueError(f"다음-아이템 학습에 쓸 수 있는(시퀀스 길이 {config.MIN_SEQ_LEN} 이상) 유저가 없습니다.")

    loader = DataLoader(train_dataset, batch_size=min(batch_size, len(train_dataset)), shuffle=True)

    model = SASRec(
        vocab_size=len(vocab),
        max_len=config.MAX_SEQ_LEN,
        embed_dim=config.EMBED_DIM,
        n_heads=config.N_HEADS,
        n_layers=config.N_LAYERS,
        ffn_dim=config.FFN_DIM,
        dropout=config.DROPOUT,
        genre_vocab_size=len(side_vocabs.genre),
        ad_type_vocab_size=len(side_vocabs.ad_type),
        connection_type_vocab_size=len(side_vocabs.connection_type),
    )

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = torch.nn.CrossEntropyLoss(ignore_index=IGNORE_INDEX)

    model.train()
    for epoch in range(1, num_epochs + 1):
        total_loss = 0.0
        total_tokens = 0
        for _, input_ids, target_ids, _lengths, genre_ids, ad_type_ids, connection_type_ids in tqdm(
            loader, desc=f"epoch {epoch}/{num_epochs}", leave=False, mininterval=5.0
        ):
            optimizer.zero_grad()
            logits = model(input_ids, genre_ids, ad_type_ids, connection_type_ids)  # (B, L, V)
            loss = criterion(logits.reshape(-1, logits.size(-1)), target_ids.reshape(-1))

            loss.backward()
            optimizer.step()

            n_valid = (target_ids != IGNORE_INDEX).sum().item()
            total_loss += loss.item() * n_valid
            total_tokens += n_valid

        avg_loss = total_loss / max(total_tokens, 1)
        logger.info("epoch %d/%d loss=%.4f", epoch, num_epochs, avg_loss)
        print(f"[epoch {epoch}/{num_epochs}] loss={avg_loss:.4f}")

    _save_artifacts(model, vocab, side_vocabs, artifact_dir)


def main():
    parser = argparse.ArgumentParser(description="top500_media_visit 시퀀스에 SASRec을 학습하고 모델을 저장한다.")
    parser.add_argument("--input", help="학습 소스 CSV 경로 (생략 시 data/top500*.csv 중 최신 파일 자동 선택)")
    parser.add_argument("--output", help=f"모델 아티팩트 저장 디렉터리 (생략 시 기본 경로: {config.ARTIFACT_DIR})")
    parser.add_argument(
        "--config",
        help="dataset_path/output_model_path/num_epochs/batch_size/learning_rate를 담은 JSON 설정 파일 "
        "(config/train_config.example.json 참고). --input/--output을 같이 주면 그 값이 우선한다.",
    )
    args = parser.parse_args()

    cfg = load_train_config(args.config) if args.config else {}
    input_path = args.input or cfg.get("dataset_path")
    artifact_dir = args.output or cfg.get("output_model_path")
    num_epochs = cfg.get("num_epochs", config.NUM_EPOCHS)
    batch_size = cfg.get("batch_size", config.BATCH_SIZE)
    lr = cfg.get("learning_rate", config.LEARNING_RATE)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=== media_sequence 임베딩(SASRec) 학습 시작 ===")
    train(num_epochs=num_epochs, batch_size=batch_size, lr=lr, input_path=input_path, artifact_dir=artifact_dir)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
