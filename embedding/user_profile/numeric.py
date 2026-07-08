# embedding/user_profile/numeric.py
#
# 수치형 필드 표준화. 결측은 0으로 채우되, 별도 마스크로 남겨 학습 시
# "결측을 0이라는 실제 값처럼 재구성하려 드는" 왜곡을 손실 계산에서 제외할 수 있게 한다.

import json
from pathlib import Path
from typing import Tuple, Union

import numpy as np
import pandas as pd


class NumericScaler:
    def __init__(self, mean: float, std: float, log1p: bool):
        self.mean = mean
        self.std = std if std > 1e-6 else 1.0
        self.log1p = log1p

    @classmethod
    def fit(cls, values: pd.Series, log1p: bool) -> "NumericScaler":
        v = pd.to_numeric(values, errors="coerce")
        if log1p:
            v = np.log1p(v.clip(lower=0))
        mean = v.mean(skipna=True)
        std = v.std(skipna=True)
        return cls(
            mean=float(mean) if pd.notna(mean) else 0.0,
            std=float(std) if pd.notna(std) else 1.0,
            log1p=log1p,
        )

    def transform(self, values: pd.Series) -> Tuple[np.ndarray, np.ndarray]:
        """반환: (표준화된 값, 결측 여부 마스크(1=존재, 0=결측))."""
        v = pd.to_numeric(values, errors="coerce")
        mask = (~v.isna()).astype(np.float32).to_numpy()
        v = v.fillna(0.0)
        if self.log1p:
            v = np.log1p(v.clip(lower=0))
        scaled = ((v - self.mean) / self.std).to_numpy(dtype=np.float32)
        scaled = scaled * mask  # 결측치는 표준화 후에도 0으로 고정
        return scaled, mask

    def to_dict(self) -> dict:
        return {"mean": self.mean, "std": self.std, "log1p": self.log1p}

    @classmethod
    def from_dict(cls, d: dict) -> "NumericScaler":
        return cls(mean=d["mean"], std=d["std"], log1p=d["log1p"])

    @classmethod
    def load(cls, path: Union[str, Path]) -> "NumericScaler":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
