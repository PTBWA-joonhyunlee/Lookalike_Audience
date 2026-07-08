# inference/media_sequence.py
#
# 학습된 아티팩트(model.pt / vocab_media.json / 보조 피처 vocab)를 재사용해서 재학습 없이
# 새 top500_media_visit(이벤트 그레인) 데이터를 임베딩할 때 쓴다.
#
# CLI 실행: .venv\Scripts\python.exe -m inference.media_sequence --input <csv> [--output <csv>] [--model-dir <dir>]
#   --model-dir을 생략하면 config.ARTIFACT_DIR(마지막으로 train/media_sequence.py를 돌려 저장된
#   기본/pretrained 모델)을 쓴다.
# --config: dataset_path/output_path/model_dir를 담은 JSON (config/inference_config.example.json
#   참고). --input/--output/--model-dir을 같이 주면 그 값이 config보다 우선한다.

import argparse
import os
from datetime import datetime
from typing import Optional, Tuple, Union

import pandas as pd
import torch
from torch.utils.data import DataLoader

from embedding.common.inference_config import load_inference_config
from embedding.common.vocab import CategoryVocab
from embedding.media_sequence import config
from embedding.media_sequence.dataset import MediaSequenceInferenceDataset
from embedding.media_sequence.model import SASRec
from embedding.media_sequence.side_features import SideFeatureVocabs


def load_artifacts(
    artifact_dir: Optional[Union[str, os.PathLike]] = None,
) -> Tuple[SASRec, CategoryVocab, SideFeatureVocabs]:
    """artifact_dir을 생략하면 config.ARTIFACT_DIR(기본/pretrained 모델 경로)을 쓴다."""
    artifact_dir = artifact_dir or config.ARTIFACT_DIR

    vocab = CategoryVocab.load(os.path.join(str(artifact_dir), "vocab_media.json"))
    side_vocabs = SideFeatureVocabs.load(artifact_dir)

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
    model.load_state_dict(
        torch.load(os.path.join(str(artifact_dir), "model.pt"), map_location="cpu")
    )
    model.eval()
    return model, vocab, side_vocabs


def encode_dataset(model: SASRec, dataset: MediaSequenceInferenceDataset, batch_size: int = 256) -> pd.DataFrame:
    model.eval()
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    ids, embeds = [], []
    with torch.no_grad():
        for batch_ids, input_ids, lengths, genre_ids, ad_type_ids, connection_type_ids in loader:
            z = model.pooled_embedding(input_ids, lengths, genre_ids, ad_type_ids, connection_type_ids)
            ids.extend(batch_ids)
            embeds.append(z)

    embeds_t = torch.cat(embeds, dim=0)
    emb_cols = [f"emb_{i:02d}" for i in range(embeds_t.shape[1])]
    out = pd.DataFrame(embeds_t.numpy(), columns=emb_cols)
    out.insert(0, config.ID_COL, ids)
    return out


def encode(df: pd.DataFrame, artifact_dir: Optional[Union[str, os.PathLike]] = None) -> pd.DataFrame:
    """artifact_dir을 지정하면 그 경로의 학습된 모델로, 생략하면 기본/pretrained 모델로 인코딩한다."""
    model, vocab, side_vocabs = load_artifacts(artifact_dir)
    dataset = MediaSequenceInferenceDataset(
        df,
        vocab,
        config.MAX_SEQ_LEN,
        id_col=config.ID_COL,
        media_col=config.MEDIA_COL,
        ts_col=config.TS_COL,
        genre_col=config.CONTENT_GENRE_COL,
        ad_type_col=config.AD_TYPE_COL,
        connection_type_col=config.CONNECTION_TYPE_COL,
        side_vocabs=side_vocabs,
        max_genres=config.MAX_GENRES_PER_EVENT,
    )
    return encode_dataset(model, dataset)


def main():
    parser = argparse.ArgumentParser(description="학습된 media_sequence(SASRec) 모델로 재학습 없이 임베딩을 뽑는다.")
    parser.add_argument("--input", help="인코딩할 CSV 경로 (01_top500_media_visit.sql과 같은 이벤트 그레인 스키마)")
    parser.add_argument("--output", help="결과 저장 경로 (생략 시 data/embeddings/media_sequence_scored_<날짜>.csv)")
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
        output = os.path.join(str(config.EMBEDDINGS_DIR), f"media_sequence_scored_{today}.csv")
    emb_df.to_csv(output, index=False)
    print(f"[INFO] media_sequence 임베딩 저장: {output} (유저 {len(emb_df):,}명, 차원 {config.EMBED_DIM})")


if __name__ == "__main__":
    main()
