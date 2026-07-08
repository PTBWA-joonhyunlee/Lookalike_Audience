# train/user_profile.py
#
# user_profile Autoencoder를 학습하고 아티팩트(model.pt, vocab_*.json, scaler_*.json)를
# 저장한다. 임베딩 추출은 하지 않는다 — 학습된 모델로 임베딩을 뽑으려면 inference/user_profile.py를 쓴다.
# 실행: .venv\Scripts\python.exe -m train.user_profile [--input <csv>] [--output <모델 저장 경로>] [--config <json>]
# 입력: --input 생략 시 data/user_profile*.csv 중 최신 파일 자동 선택 (02_user_profile.sql 결과)
# 출력: --output 생략 시 data/models/user_profile/ (model.pt, vocab_*.json, scaler_*.json —
#       inference/user_profile.py가 재사용)
# --config: dataset_path/output_model_path/num_epochs/batch_size/learning_rate를 담은 JSON
#       (config/train_config.example.json 참고). --input/--output을 같이 주면 그 값이 config보다
#       우선한다. num_epochs/batch_size/learning_rate는 config에만 있으면 적용되고, 없으면
#       embedding/user_profile/config.py의 기본값을 쓴다.
#
# 모델/데이터셋/전처리 정의(embedding/user_profile/)는 이 학습 루프와 inference/user_profile.py가
# 공유하는 자원이라 이 폴더로 옮기지 않았다 — 자세한 구조는 embedding/user_profile/, README.md 참고.

import argparse
import json
import logging
import os
from typing import Dict, Optional

import pandas as pd
import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from embedding.common.io import latest_file
from embedding.common.train_config import load_train_config
from embedding.common.vocab import CategoryVocab
from embedding.user_profile import config
from embedding.user_profile.dataset import UserProfileDataset
from embedding.user_profile.model import UserProfileAutoencoder
from embedding.user_profile.numeric import NumericScaler

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
    logger.info("user_profile 소스: %s", path)
    print(f"[INFO] user_profile 소스: {path}")

    df = pd.read_csv(path)

    required = [config.ID_COL, *config.CATEGORICAL_FIELDS, *config.NUMERIC_FIELDS]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"소스 CSV에 누락된 컬럼: {missing}")

    before = len(df)
    df = df.drop_duplicates(subset=[config.ID_COL], keep="first").reset_index(drop=True)
    if len(df) != before:
        logger.warning("%s 기준 중복 %d행 제거", config.ID_COL, before - len(df))
        print(f"[WARN] {config.ID_COL} 기준 중복 {before - len(df)}행 제거됨 — 소스 쿼리 확인 필요")

    return df


def _fit_vocabs(df: pd.DataFrame) -> Dict[str, CategoryVocab]:
    vocabs = {}
    for field, spec in config.CATEGORICAL_FIELDS.items():
        series = spec["preprocess"](df[field])
        vocabs[field] = CategoryVocab.build(series, min_freq=spec["min_freq"], max_size=spec["max_size"])
        logger.info("vocab[%s] size=%d", field, len(vocabs[field]))
    return vocabs


def _fit_scalers(df: pd.DataFrame) -> Dict[str, NumericScaler]:
    return {
        field: NumericScaler.fit(df[field], log1p=spec["log1p"])
        for field, spec in config.NUMERIC_FIELDS.items()
    }


def _save_artifacts(
    model: UserProfileAutoencoder,
    cat_vocabs: Dict[str, CategoryVocab],
    numeric_scalers: Dict[str, NumericScaler],
    artifact_dir: Optional[str] = None,
) -> None:
    artifact_dir = artifact_dir or config.ARTIFACT_DIR
    os.makedirs(artifact_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(str(artifact_dir), "model.pt"))
    for field, vocab in cat_vocabs.items():
        vocab.save(os.path.join(str(artifact_dir), f"vocab_{field}.json"))
    for field, scaler in numeric_scalers.items():
        path = os.path.join(str(artifact_dir), f"scaler_{field}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(scaler.to_dict(), fh, ensure_ascii=False, indent=2)
    print(f"[INFO] 모델/vocab/scaler 저장: {artifact_dir}")


def train(
    num_epochs: int = config.NUM_EPOCHS,
    batch_size: int = config.BATCH_SIZE,
    lr: float = config.LEARNING_RATE,
    input_path: Optional[str] = None,
    artifact_dir: Optional[str] = None,
) -> None:
    df = _load_source(input_path)

    cat_vocabs = _fit_vocabs(df)
    numeric_scalers = _fit_scalers(df)

    dataset = UserProfileDataset(df, config.CATEGORICAL_FIELDS, cat_vocabs, numeric_scalers, id_col=config.ID_COL)
    loader = DataLoader(dataset, batch_size=min(batch_size, len(dataset)), shuffle=True)

    cat_embed_dims = {f: config.CATEGORICAL_FIELDS[f]["embed_dim"] for f in cat_vocabs}
    model = UserProfileAutoencoder(
        cat_vocabs=cat_vocabs,
        cat_embed_dims=cat_embed_dims,
        numeric_fields=list(numeric_scalers.keys()),
        hidden_dim=config.HIDDEN_DIM,
        embed_dim=config.EMBED_DIM,
    )

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    cat_criterion = torch.nn.CrossEntropyLoss()

    model.train()
    for epoch in range(1, num_epochs + 1):
        total_loss = 0.0
        for _, cat, numeric, numeric_mask in tqdm(loader, desc=f"epoch {epoch}/{num_epochs}", leave=False, mininterval=5.0):
            optimizer.zero_grad()
            _, cat_logits, numeric_recon = model(cat, numeric)

            loss = sum(cat_criterion(cat_logits[f], cat[f]) for f in model.cat_fields)
            if numeric_recon is not None:
                sq_err = (numeric_recon - numeric) ** 2 * numeric_mask
                denom = numeric_mask.sum().clamp(min=1.0)
                loss = loss + sq_err.sum() / denom

            loss.backward()
            optimizer.step()
            total_loss += loss.item() * numeric.shape[0]

        avg_loss = total_loss / len(dataset)
        logger.info("epoch %d/%d loss=%.4f", epoch, num_epochs, avg_loss)
        print(f"[epoch {epoch}/{num_epochs}] loss={avg_loss:.4f}")

    _save_artifacts(model, cat_vocabs, numeric_scalers, artifact_dir)


def main():
    parser = argparse.ArgumentParser(description="user_profile Autoencoder를 학습하고 모델을 저장한다.")
    parser.add_argument("--input", help="학습 소스 CSV 경로 (생략 시 data/user_profile*.csv 중 최신 파일 자동 선택)")
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
    print("=== user_profile 임베딩(Autoencoder) 학습 시작 ===")
    train(num_epochs=num_epochs, batch_size=batch_size, lr=lr, input_path=input_path, artifact_dir=artifact_dir)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
