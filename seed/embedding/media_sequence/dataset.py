# seed/embedding/media_sequence/dataset.py
#
# build_features.py가 만든 media_features.npz(디바이스별 가변 길이 인코딩 시퀀스, 최대
# MAX_SEQ_LEN+1개)를 SASRec 학습/추론용 고정 길이 텐서로 바꾼다. 시퀀스 길이가 디바이스마다
# 달라서(패딩 전) 여기서 개별적으로 잘라야 하는데, 이 로직 자체는 옛 addi 트랙
# embedding/media_sequence/dataset.py의 build_sequences/encode_padded와 동일한 아이디어다
# (다만 원본은 raw CSV에서 매번 다시 만들었고, 여기서는 build_features.py가 미리 인코딩해둔
# npz를 읽기만 한다).

from typing import List

import numpy as np
import torch
from torch.utils.data import Dataset

IGNORE_INDEX = -100  # nn.CrossEntropyLoss 기본 ignore_index와 맞춤 (target 패딩용)


def _pad(arr: np.ndarray, width: int, pad_value) -> np.ndarray:
    """가변 길이 1D 배열 -> 오른쪽에 pad_value로 채운 고정 길이(width) 배열. 뒤쪽(최근) width개만 사용."""
    arr = arr[-width:]
    out = np.full(width, pad_value, dtype=np.int64)
    out[: len(arr)] = arr
    return out


class MediaSequenceDataset(Dataset):
    """다음-아이템 예측 학습용. build_features.py가 디바이스당 최대 (MAX_SEQ_LEN+1)개의
    최근 이벤트로 이미 잘라뒀으므로, 여기서는 앞쪽 N-1개(input)/뒤쪽 N-1개(target)로 한 칸
    밀어서 나누기만 한다. 원본 이벤트 수(shift 전)가 min_len 미만인 디바이스는 다음-아이템
    학습 신호가 너무 약해 제외한다(inference는 별도 Dataset이라 이 필터와 무관하게 포함)."""

    def __init__(self, npz_path, max_len: int, min_len: int = 5):
        data = np.load(npz_path, allow_pickle=True)
        self.max_len = max_len
        self.ids: List[str] = []
        self.inputs, self.targets, self.lengths = [], [], []
        self.inventory, self.ad_types, self.connection_types = [], [], []
        self.skipped = 0

        for uid, m, inv, ad, conn in zip(
            data["device_ifa"], data["media_ids"], data["inventory_type_ids"],
            data["ad_type_ids"], data["connection_type_ids"],
        ):
            if len(m) < min_len:
                self.skipped += 1
                continue

            inp_m, tgt_m = m[:-1], m[1:]
            length = len(inp_m)

            self.ids.append(str(uid))
            self.inputs.append(_pad(inp_m, max_len, 0))
            self.targets.append(_pad(tgt_m, max_len, IGNORE_INDEX))
            self.lengths.append(length)
            self.inventory.append(_pad(inv[:-1], max_len, 0))
            self.ad_types.append(_pad(ad[:-1], max_len, 0))
            self.connection_types.append(_pad(conn[:-1], max_len, 0))

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return (
            self.ids[idx],
            torch.tensor(self.inputs[idx], dtype=torch.long),
            torch.tensor(self.targets[idx], dtype=torch.long),
            self.lengths[idx],
            torch.tensor(self.inventory[idx], dtype=torch.long),
            torch.tensor(self.ad_types[idx], dtype=torch.long),
            torch.tensor(self.connection_types[idx], dtype=torch.long),
        )


class MediaSequenceInferenceDataset(Dataset):
    """학습 여부와 무관하게 유저 임베딩을 뽑기 위한 추론 전용 Dataset. min_len 미만인
    디바이스는 학습 때와 동일한 기준으로 제외한다(신뢰하기 어려운 임베딩이 lookalike
    스코어링에 섞이지 않도록 — inference/media_sequence.py 참고)."""

    def __init__(self, npz_path, max_len: int, min_len: int = 5):
        data = np.load(npz_path, allow_pickle=True)
        self.ids: List[str] = []
        self.inputs, self.lengths = [], []
        self.inventory, self.ad_types, self.connection_types = [], [], []

        for uid, m, inv, ad, conn in zip(
            data["device_ifa"], data["media_ids"], data["inventory_type_ids"],
            data["ad_type_ids"], data["connection_type_ids"],
        ):
            if len(m) < min_len:
                continue
            m2, inv2, ad2, conn2 = m[-max_len:], inv[-max_len:], ad[-max_len:], conn[-max_len:]

            self.ids.append(str(uid))
            self.inputs.append(_pad(m2, max_len, 0))
            self.lengths.append(max(len(m2), 1))
            self.inventory.append(_pad(inv2, max_len, 0))
            self.ad_types.append(_pad(ad2, max_len, 0))
            self.connection_types.append(_pad(conn2, max_len, 0))

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return (
            self.ids[idx],
            torch.tensor(self.inputs[idx], dtype=torch.long),
            self.lengths[idx],
            torch.tensor(self.inventory[idx], dtype=torch.long),
            torch.tensor(self.ad_types[idx], dtype=torch.long),
            torch.tensor(self.connection_types[idx], dtype=torch.long),
        )
