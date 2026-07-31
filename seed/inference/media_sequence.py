# seed/inference/media_sequence.py
#
# 학습된 model.pt(encoder)로 media_features.npz 전체 디바이스의 임베딩(m_0..m_63)을 뽑는다.
# segment_features 추론과 동일하게, population 구분 없이 seed+pool+candidate 전체를 한 번에
# 인코딩하고 device_ifa로 나중에 다시 나눈다.
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m inference.media_sequence [--output <csv>] [--batch-size 4096]

import argparse
import os

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from embedding.common.device import resolve_device
from embedding.common.vocab import CategoryVocab
from embedding.media_sequence import config
from embedding.media_sequence.dataset import MediaSequenceInferenceDataset
from embedding.media_sequence.model import SASRec


def load_model(device: torch.device, model_path=None) -> SASRec:
    media_vocab = CategoryVocab.load(config.MEDIA_VOCAB_PATH)
    inventory_vocab = CategoryVocab.load(config.INVENTORY_TYPE_VOCAB_PATH)
    ad_type_vocab = CategoryVocab.load(config.AD_TYPE_VOCAB_PATH)
    connection_type_vocab = CategoryVocab.load(config.CONNECTION_TYPE_VOCAB_PATH)

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
    ).to(device)
    model.load_state_dict(torch.load(model_path or config.MODEL_PATH, map_location=device))
    model.eval()
    return model


def run(output_path: str = None, batch_size: int = 4096, device: str = "auto", model_path=None) -> None:
    device = resolve_device(device)
    print(f"[INFO] device={device}")

    model_path = model_path or config.MODEL_PATH
    print(f"[INFO] 모델 로드: {model_path}")
    model = load_model(device, model_path)
    dataset = MediaSequenceInferenceDataset(
        config.FEATURES_NPZ_PATH, max_len=config.MAX_SEQ_LEN, min_len=config.MIN_SEQ_LEN
    )
    print(f"[INFO] 이벤트 {config.MIN_SEQ_LEN}개 미만 제외 후 임베딩 대상: {len(dataset):,}개 디바이스")
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    ids, chunks = [], []
    with torch.no_grad():
        for batch_ids, input_ids, lengths, inv_ids, ad_ids, conn_ids in tqdm(loader, mininterval=5.0):
            z = model.pooled_embedding(
                input_ids.to(device),
                lengths.to(device),
                inv_ids.to(device),
                ad_ids.to(device),
                conn_ids.to(device),
            )
            ids.extend(batch_ids)
            chunks.append(z.cpu().numpy())

    out = pd.DataFrame(np.concatenate(chunks), columns=[f"m_{i}" for i in range(config.EMBED_DIM)])
    out.insert(0, config.ID_COL, ids)

    output_path = output_path or str(config.ARTIFACT_DIR / "media_embeddings.csv")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out.to_csv(output_path, index=False)
    print(f"[INFO] media 임베딩 저장: {output_path} ({len(out):,}개 디바이스, {config.EMBED_DIM}dim)")


def main():
    parser = argparse.ArgumentParser(description="학습된 media_sequence(SASRec)로 재학습 없이 임베딩을 뽑는다.")
    parser.add_argument("--output", help=f"결과 CSV 저장 경로 (생략 시 기본값: {config.ARTIFACT_DIR / 'media_embeddings.csv'})")
    parser.add_argument("--model-path", help=f"모델 체크포인트 경로 (생략 시 기본값: {config.MODEL_PATH}, 마지막 epoch)")
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    run(output_path=args.output, batch_size=args.batch_size, device=args.device, model_path=args.model_path)


if __name__ == "__main__":
    main()
