# seed/scoring/dataset.py
#
# Variant(config.VARIANTS)가 가리키는 임베딩 CSV 1~2개 + seed/pool device_ifa 목록으로
# 학습용 (X, y) 텐서를 만든다. segment/media 임베딩 CSV는 둘 다 population 구분 없이
# seed+pool+candidate 전체를 한 번에 인코딩한 결과라, 여기서 seed/pool/candidate 중
# 어디에 속하는지는 device_ifa 목록으로만 구분한다.

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from . import config
from .config import Variant


def load_ids(csv_path) -> set:
    return set(pd.read_csv(csv_path, usecols=[config.ID_COL], dtype=str)[config.ID_COL])


def _load_source(csv_path, embed_cols) -> pd.DataFrame:
    # build_features.py(segment_features)와 build.py(media_sequence) 둘 다 04c_seed/
    # 05c_pool/07c_candidate 세 소스를 device_ifa 중복 제거 없이 처리한다 — 4~5월 pool
    # 표본이면서 6월 candidate 조건도 만족하는 디바이스(2026-07-30 확인: segment 기준
    # 33,266명)는 임베딩이 두 번 계산돼 중복 행으로 존재할 수 있다. 그대로 두면 학습
    # 데이터가 살짝 부풀려지고 candidate 스코어링 결과에도 중복 행이 남으므로 여기서
    # 한 번에 제거한다(첫 번째 값 유지 — 중복 행은 같은 원본 데이터에서 나와 값도 사실상 동일).
    df = pd.read_csv(csv_path, dtype={config.ID_COL: str}, usecols=[config.ID_COL, *embed_cols])
    return df.drop_duplicates(subset=[config.ID_COL], keep="first").reset_index(drop=True)


def load_embeddings(variant: Variant) -> pd.DataFrame:
    """variant.sources가 1개면 그 임베딩 그대로, 2개(combined)면 device_ifa 기준 inner
    join으로 두 임베딩을 이어붙인다 — media 쪽엔 이벤트 5개 미만이라 임베딩이 없는
    디바이스가 있어서(embedding/media_sequence/config.MIN_SEQ_LEN), combined의 표본은
    "segment와 media 임베딩이 둘 다 있는 디바이스"로 자연히 좁혀진다."""
    frames = [_load_source(csv_path, embed_cols) for csv_path, embed_cols in variant.sources]
    if len(frames) == 1:
        return frames[0]
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=config.ID_COL, how="inner")
    return merged


def build_labeled_frame(embeddings: pd.DataFrame, variant: Variant) -> pd.DataFrame:
    """seed=1, pool=0 라벨을 붙인 학습용 프레임. candidate는 여기 포함되지 않는다.
    variant.seed_ids_csv/pool_ids_csv를 쓴다 — 트랙마다 pool 정의가 달라(segment/media
    분리, config.py 참고) variant별로 다른 population 목록을 써야 한다."""
    seed_ids = load_ids(variant.seed_ids_csv)
    pool_ids = load_ids(variant.pool_ids_csv)

    df = embeddings[embeddings[config.ID_COL].isin(seed_ids | pool_ids)].copy()
    df["label"] = df[config.ID_COL].isin(seed_ids).astype("float32")
    return df


class EmbeddingLabelDataset(Dataset):
    def __init__(self, df: pd.DataFrame, embed_cols):
        self.ids = df[config.ID_COL].to_numpy()
        self.x = df[embed_cols].to_numpy(dtype=np.float32)
        self.y = df["label"].to_numpy(dtype=np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return torch.from_numpy(self.x[idx]), torch.tensor(self.y[idx])
