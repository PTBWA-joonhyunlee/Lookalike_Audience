# seed/scoring/dataset.py
#
# Variant(config.VARIANTS)가 가리키는 segment 임베딩 CSV + seed/pool device_ifa 목록으로
# 학습용 (X, y) 텐서를 만든다. 임베딩 CSV는 population 구분 없이 seed+pool+candidate
# 전체를 한 번에 인코딩한 결과라, 여기서 seed/pool/candidate 중 어디에 속하는지는
# device_ifa 목록으로만 구분한다.

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from . import config
from .config import Variant


def load_ids(csv_path) -> set:
    return set(pd.read_csv(csv_path, usecols=[config.ID_COL], dtype=str)[config.ID_COL])


def _load_source(csv_path, embed_cols) -> pd.DataFrame:
    # build_features.py(segment_features)는 04c_seed/05c_pool/07c_candidate 세 소스를
    # device_ifa 중복 제거 없이 처리한다 — 4~5월 pool 표본이면서 6월 candidate 조건도
    # 만족하는 디바이스(2026-07-30 확인: segment 기준 33,266명)는 임베딩이 두 번 계산돼
    # 중복 행으로 존재할 수 있다. 그대로 두면 학습 데이터가 살짝 부풀려지고 candidate
    # 스코어링 결과에도 중복 행이 남으므로 여기서 한 번에 제거한다(첫 번째 값 유지 —
    # 중복 행은 같은 원본 데이터에서 나와 값도 사실상 동일).
    df = pd.read_csv(csv_path, dtype={config.ID_COL: str}, usecols=[config.ID_COL, *embed_cols])
    return df.drop_duplicates(subset=[config.ID_COL], keep="first").reset_index(drop=True)


def load_embeddings(variant: Variant) -> pd.DataFrame:
    """variant.sources는 지금은 항상 1개(segment 임베딩)라 그대로 반환한다."""
    frames = [_load_source(csv_path, embed_cols) for csv_path, embed_cols in variant.sources]
    if len(frames) == 1:
        return frames[0]
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=config.ID_COL, how="inner")
    return merged


def build_labeled_frame(embeddings: pd.DataFrame, variant: Variant) -> pd.DataFrame:
    """seed=1, pool=0 라벨을 붙인 학습용 프레임. candidate는 여기 포함되지 않는다.
    variant.seed_ids_csv/pool_ids_csv를 쓴다 — seed 브랜드마다 pool 정의가 달라질 수
    있어 variant별로 다른 population 목록을 써야 한다."""
    seed_ids = load_ids(variant.seed_ids_csv)
    pool_ids = load_ids(variant.pool_ids_csv)

    df = embeddings[embeddings[config.ID_COL].isin(seed_ids | pool_ids)].copy()
    df["label"] = df[config.ID_COL].isin(seed_ids).astype("float32")
    return df


def build_multilabel_frame(embeddings: pd.DataFrame, variant) -> pd.DataFrame:
    """MultiLabelVariant용 학습 프레임. 라벨 컬럼 label_<key>는 해당 seed 소속 여부(멀티핫) —
    pool에 있으면서 seed에도 있는 유저는 seed 라벨을 따른다(pool은 "일반 모집단" 표본이라
    seed 유저가 섞여 있을 수 있음). pool에만 있는 유저는 전부 0. candidate는 포함하지 않는다."""
    seed_sets = {lb.key: load_ids(lb.seed_ids_csv) for lb in variant.labels}
    pool_ids = load_ids(variant.pool_ids_csv)
    all_ids = set(pool_ids).union(*seed_sets.values())

    df = embeddings[embeddings[config.ID_COL].isin(all_ids)].copy()
    for key, ids in seed_sets.items():
        df[f"label_{key}"] = df[config.ID_COL].isin(ids).astype("float32")
    return df


class MultiLabelDataset(Dataset):
    def __init__(self, df: pd.DataFrame, embed_cols, label_keys):
        # pandas copy-on-write로 to_numpy() 결과가 읽기 전용일 수 있어 torch.from_numpy 경고가
        # 난다 — 쓰기 가능한 배열로 보장해둔다.
        self.x = np.require(df[embed_cols].to_numpy(dtype=np.float32), requirements="W")
        self.y = np.require(df[[f"label_{k}" for k in label_keys]].to_numpy(dtype=np.float32), requirements="W")

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(self, idx: int):
        return torch.from_numpy(self.x[idx]), torch.from_numpy(self.y[idx])


class EmbeddingLabelDataset(Dataset):
    def __init__(self, df: pd.DataFrame, embed_cols):
        self.ids = df[config.ID_COL].to_numpy()
        self.x = df[embed_cols].to_numpy(dtype=np.float32)
        self.y = df["label"].to_numpy(dtype=np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return torch.from_numpy(self.x[idx]), torch.tensor(self.y[idx])
