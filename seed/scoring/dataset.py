# seed/scoring/dataset.py
#
# 임베딩 CSV(inference/segment_features.py 출력) + seed/pool device_ifa 목록으로 학습용
# (X, y) 텐서를 만든다.

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from . import config


def load_ids(csv_path) -> set:
    return set(pd.read_csv(csv_path, usecols=[config.ID_COL], dtype=str)[config.ID_COL])


def load_embeddings() -> pd.DataFrame:
    # build_features.py가 04c_seed/05c_pool/07c_candidate 세 소스 CSV를 device_ifa 중복
    # 제거 없이 그냥 concat한다 — 4~5월 pool 표본이면서 6월 candidate 조건도 만족하는
    # 디바이스(2026-07-30 확인: 33,266명)는 세그먼트 임베딩이 두 번 계산돼 두 행으로
    # 중복 존재한다. 그대로 두면 학습 데이터가 살짝 부풀려지고(pool 쪽, 영향 미미), 무엇보다
    # candidate 스코어링 결과에 같은 device_ifa가 중복 행으로 나온다 — 여기서 한 번에
    # 제거한다(첫 번째 값 유지, 중복 행은 같은 segment 데이터에서 나와 값도 사실상 동일).
    df = pd.read_csv(config.EMBEDDINGS_CSV, dtype={config.ID_COL: str})
    return df.drop_duplicates(subset=[config.ID_COL], keep="first").reset_index(drop=True)


def build_labeled_frame(embeddings: pd.DataFrame) -> pd.DataFrame:
    """seed=1, pool=0 라벨을 붙인 학습용 프레임. candidate는 여기 포함되지 않는다."""
    seed_ids = load_ids(config.SEED_IDS_CSV)
    pool_ids = load_ids(config.POOL_IDS_CSV)

    df = embeddings[embeddings[config.ID_COL].isin(seed_ids | pool_ids)].copy()
    df["label"] = df[config.ID_COL].isin(seed_ids).astype("float32")
    return df


class EmbeddingLabelDataset(Dataset):
    def __init__(self, df: pd.DataFrame):
        self.ids = df[config.ID_COL].to_numpy()
        self.x = df[config.EMBED_COLS].to_numpy(dtype=np.float32)
        self.y = df["label"].to_numpy(dtype=np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return torch.from_numpy(self.x[idx]), torch.tensor(self.y[idx])
