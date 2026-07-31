# seed/inference/segment_features.py
#
# 학습된 segment_features Autoencoder(model.pt)의 인코더만 실행해서 device_ifa별
# z(32dim) 임베딩을 CSV로 저장한다. 재학습은 하지 않는다.
#
# build_features.py가 만든 segment_features.npz는 seed/pool/candidate 구분 없이
# 5,710,059명이 합쳐져 있다 — 이 스크립트도 population 구분 없이 전체에 대해 한 번에
# 임베딩을 뽑고, 어느 population인지는 scoring/ 쪽에서 seed/pool/candidate 각 쿼리
# 산출 CSV(04c/05c/07c_*_segment.csv)의 device_ifa 목록으로 다시 나눈다.
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m inference.segment_features
#   [--input <npz>] [--model-dir <model.pt 있는 폴더>] [--output <저장 경로>]

import argparse
import os

import pandas as pd
import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from embedding.common.device import resolve_device
from embedding.common.vocab import CategoryVocab
from embedding.segment_features import config
from embedding.segment_features.bert_lookup import SegmentEmbeddingLookup
from embedding.segment_features.dataset import SegmentFeaturesDataset
from embedding.segment_features.model import SegmentFeaturesAutoencoder


def load_model(model_dir: str, device: torch.device) -> SegmentFeaturesAutoencoder:
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
    state_path = os.path.join(model_dir, "model.pt")
    model.load_state_dict(torch.load(state_path, map_location=device))
    model.eval()
    return model


def run(input_path=None, model_dir=None, output_path=None, batch_size=4096, device="auto"):
    device = resolve_device(device)
    print(f"[INFO] device={device}")

    npz_path = input_path or str(config.ARTIFACT_DIR / "segment_features.npz")
    model_dir = model_dir or str(config.ARTIFACT_DIR)
    output_path = output_path or str(config.ARTIFACT_DIR / "segment_embeddings.csv")

    dataset = SegmentFeaturesDataset(npz_path)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
    model = load_model(model_dir, device)

    ids = []
    z_chunks = []
    with torch.no_grad():
        for id_batch, batch in tqdm(loader, desc="encode", mininterval=5.0):
            batch = {k: v.to(device) for k, v in batch.items()}
            z, _ = model.encode(batch)
            ids.extend(id_batch)
            z_chunks.append(z.cpu().numpy())

    import numpy as np
    z_arr = np.concatenate(z_chunks, axis=0)
    out = pd.DataFrame(z_arr, columns=[f"z_{i}" for i in range(z_arr.shape[1])])
    out.insert(0, config.ID_COL, ids)
    out.to_csv(output_path, index=False)

    print(f"[INFO] {len(ids)}명 -> {output_path}")


def main():
    parser = argparse.ArgumentParser(description="학습된 segment_features 모델로 임베딩을 추출한다.")
    parser.add_argument("--input", help="segment_features.npz 경로")
    parser.add_argument("--model-dir", help="model.pt가 있는 디렉터리")
    parser.add_argument("--output", help="임베딩 CSV 저장 경로")
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()

    run(input_path=args.input, model_dir=args.model_dir, output_path=args.output,
        batch_size=args.batch_size, device=args.device)


if __name__ == "__main__":
    main()
