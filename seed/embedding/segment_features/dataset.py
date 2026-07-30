# embedding/segment_features/dataset.py
#
# build_features.py가 만든 segment_features.npz(device_ifa, gender_score, age_bracket_idx,
# {group}_idx)를 그대로 감싸는 Dataset. 피처 자체(인덱스 배열)는 이미 만들어져 있으므로
# 여기서는 텐서 변환만 한다 — 실제 mean pooling(EmbeddingBag)은 model.py가 배치 단위로 한다.

import numpy as np
import torch
from torch.utils.data import Dataset

from .model import POOLED_GROUPS


class SegmentFeaturesDataset(Dataset):
    def __init__(self, npz_path):
        data = np.load(npz_path, allow_pickle=True)
        self.ids = data["device_ifa"]
        self.gender_score = data["gender_score"].astype(np.float32)
        self.age_bracket_idx = data["age_bracket_idx"].astype(np.int64)
        self.group_idx = {g: data[f"{g}_idx"].astype(np.int64) for g in POOLED_GROUPS}

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        batch = {
            "gender_score": torch.tensor(self.gender_score[idx], dtype=torch.float32),
            "age_bracket_idx": torch.tensor(self.age_bracket_idx[idx], dtype=torch.long),
        }
        for g in POOLED_GROUPS:
            batch[f"{g}_idx"] = torch.tensor(self.group_idx[g][idx], dtype=torch.long)
        return str(self.ids[idx]), batch
