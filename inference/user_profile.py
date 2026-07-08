# inference/user_profile.py
#
# 학습된 아티팩트(model.pt / vocab_*.json / numeric_scalers.json)를 재사용해서
# 재학습 없이 새 user_profile 데이터를 임베딩하고 싶을 때 쓴다.
# (나중에 top500_media_visit 시퀀스 임베딩과 합칠 때 이 함수로 z를 뽑아 쓰면 됨)
#
# CLI 실행: .venv\Scripts\python.exe -m inference.user_profile --input <csv> [--output <csv>] [--model-dir <dir>]
#   --model-dir을 생략하면 config.ARTIFACT_DIR(마지막으로 train/user_profile.py를 돌려 저장된
#   기본/pretrained 모델)을 쓴다.
# --config: dataset_path/output_path/model_dir를 담은 JSON (config/inference_config.example.json
#   참고). --input/--output/--model-dir을 같이 주면 그 값이 config보다 우선한다.

import argparse
import os
from datetime import datetime
from typing import Dict, Optional, Tuple, Union

import pandas as pd
import torch
from torch.utils.data import DataLoader

from embedding.common.inference_config import load_inference_config
from embedding.common.vocab import CategoryVocab
from embedding.user_profile import config
from embedding.user_profile.dataset import UserProfileDataset
from embedding.user_profile.model import UserProfileAutoencoder
from embedding.user_profile.numeric import NumericScaler


def load_artifacts(
    artifact_dir: Optional[Union[str, os.PathLike]] = None,
) -> Tuple[UserProfileAutoencoder, Dict[str, CategoryVocab], Dict[str, NumericScaler]]:
    """artifact_dir을 생략하면 config.ARTIFACT_DIR(기본/pretrained 모델 경로)을 쓴다."""
    artifact_dir = artifact_dir or config.ARTIFACT_DIR

    cat_vocabs: Dict[str, CategoryVocab] = {}
    for field in config.CATEGORICAL_FIELDS:
        path = os.path.join(str(artifact_dir), f"vocab_{field}.json")
        cat_vocabs[field] = CategoryVocab.load(path)

    numeric_scalers: Dict[str, NumericScaler] = {}
    for field in config.NUMERIC_FIELDS:
        path = os.path.join(str(artifact_dir), f"scaler_{field}.json")
        numeric_scalers[field] = NumericScaler.load(path)

    cat_embed_dims = {f: config.CATEGORICAL_FIELDS[f]["embed_dim"] for f in cat_vocabs}
    model = UserProfileAutoencoder(
        cat_vocabs=cat_vocabs,
        cat_embed_dims=cat_embed_dims,
        numeric_fields=list(numeric_scalers.keys()),
        hidden_dim=config.HIDDEN_DIM,
        embed_dim=config.EMBED_DIM,
    )
    model.load_state_dict(
        torch.load(os.path.join(str(artifact_dir), "model.pt"), map_location="cpu")
    )
    model.eval()
    return model, cat_vocabs, numeric_scalers


def encode_dataset(model: UserProfileAutoencoder, dataset: UserProfileDataset, batch_size: int = 512) -> pd.DataFrame:
    model.eval()
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    ids, embeds = [], []
    with torch.no_grad():
        for batch_ids, cat, numeric, _ in loader:
            z = model.encode(cat, numeric)
            ids.extend(batch_ids)
            embeds.append(z)

    embeds_t = torch.cat(embeds, dim=0)
    emb_cols = [f"emb_{i:02d}" for i in range(embeds_t.shape[1])]
    out = pd.DataFrame(embeds_t.numpy(), columns=emb_cols)
    out.insert(0, config.ID_COL, ids)
    return out


def encode(df: pd.DataFrame, artifact_dir: Optional[Union[str, os.PathLike]] = None) -> pd.DataFrame:
    """artifact_dir을 지정하면 그 경로의 학습된 모델로, 생략하면 기본/pretrained 모델로 인코딩한다."""
    model, cat_vocabs, numeric_scalers = load_artifacts(artifact_dir)
    dataset = UserProfileDataset(df, config.CATEGORICAL_FIELDS, cat_vocabs, numeric_scalers, id_col=config.ID_COL)
    return encode_dataset(model, dataset)


def main():
    parser = argparse.ArgumentParser(description="학습된 user_profile 모델로 재학습 없이 임베딩을 뽑는다.")
    parser.add_argument("--input", help="인코딩할 CSV 경로 (02_user_profile.sql과 같은 스키마)")
    parser.add_argument("--output", help="결과 저장 경로 (생략 시 data/embeddings/user_profile_scored_<날짜>.csv)")
    parser.add_argument(
        "--model-dir",
        help=f"학습된 모델 아티팩트 디렉터리 (생략 시 기본/pretrained 경로: {config.ARTIFACT_DIR})",
    )
    parser.add_argument(
        "--config",
        help="dataset_path/output_path/model_dir를 담은 JSON 설정 파일 "
        "(config/inference_config.example.json 참고). --input/--output/--model-dir을 같이 주면 그 값이 우선한다.",
    )
    args = parser.parse_args()

    cfg = load_inference_config(args.config) if args.config else {}
    input_path = args.input or cfg.get("dataset_path")
    if not input_path:
        parser.error("--input을 주거나 --config에 dataset_path를 지정해야 한다.")
    model_dir = args.model_dir or cfg.get("model_dir")

    df = pd.read_csv(input_path)
    emb_df = encode(df, artifact_dir=model_dir)

    output = args.output or cfg.get("output_path")
    if not output:
        os.makedirs(config.EMBEDDINGS_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        output = os.path.join(str(config.EMBEDDINGS_DIR), f"user_profile_scored_{today}.csv")
    emb_df.to_csv(output, index=False)
    print(f"[INFO] user_profile 임베딩 저장: {output} (유저 {len(emb_df):,}명, 차원 {config.EMBED_DIM})")


if __name__ == "__main__":
    main()
