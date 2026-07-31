# seed/embedding/common/vocab.py
#
# 범주형 필드용 문자열 <-> 정수 인덱스 vocab.
# 인덱스 0=<NA>(결측), 1=<UNK>(빈도 미달/미등록 값), 2번부터 실제 값.
# 학습 시 fit한 vocab을 파일로 저장해 추론 시에도 동일한 인덱스 매핑을 재사용한다.

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional, Union

import numpy as np
import pandas as pd

UNK_TOKEN = "<UNK>"
NA_TOKEN = "<NA>"


class CategoryVocab:
    def __init__(self, token_to_id: dict):
        self.token_to_id = token_to_id

    def __len__(self) -> int:
        return len(self.token_to_id)

    @classmethod
    def build(cls, values: Iterable, min_freq: int = 1, max_size: Optional[int] = None) -> "CategoryVocab":
        counter: Counter = Counter(cls._normalize(v) for v in values)
        return cls.build_from_counter(counter, min_freq, max_size)

    @classmethod
    def build_from_counter(
        cls, counter: Counter, min_freq: int = 1, max_size: Optional[int] = None
    ) -> "CategoryVocab":
        """이미 정규화된 토큰의 Counter로 vocab을 만든다 — media_sequence처럼 CSV를
        청크 단위로 스트리밍하며 Counter를 누적한 뒤(전체를 메모리에 올리지 않고)
        한 번에 vocab을 확정해야 할 때 build() 대신 쓴다."""
        counter = Counter(counter)
        # <NA>/<UNK>는 실제 값 빈도와 무관하게 항상 고정 인덱스로 포함시킨다.
        counter.pop(NA_TOKEN, None)
        counter.pop(UNK_TOKEN, None)

        items = [(tok, cnt) for tok, cnt in counter.items() if cnt >= min_freq]
        items.sort(key=lambda x: x[1], reverse=True)
        if max_size is not None:
            items = items[:max_size]

        token_to_id = {NA_TOKEN: 0, UNK_TOKEN: 1}
        for tok, _ in items:
            token_to_id[tok] = len(token_to_id)
        return cls(token_to_id)

    @staticmethod
    def _normalize(v) -> str:
        if v is None:
            return NA_TOKEN
        if isinstance(v, float):
            if np.isnan(v):
                return NA_TOKEN
            # pandas가 결측 섞인 정수형 컬럼(예: device_type)을 float64로 읽어
            # 4 -> 4.0 이 되는 것을 방지 (fit/encode 양쪽에서 항상 이 경로를 타므로 일관됨).
            if v.is_integer():
                return str(int(v))
            return str(v)
        s = str(v).strip()
        return s if s else NA_TOKEN

    def encode(self, v) -> int:
        token = self._normalize(v)
        return self.token_to_id.get(token, self.token_to_id[UNK_TOKEN])

    def encode_series(self, s: pd.Series) -> np.ndarray:
        return np.array([self.encode(v) for v in s], dtype=np.int64)

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(json.dumps(self.token_to_id, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "CategoryVocab":
        token_to_id = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(token_to_id)
