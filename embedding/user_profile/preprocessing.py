# 범주형 필드별 vocab 구축 전 적용하는 전처리.
# fit(vocab 구축)과 encode(추론) 양쪽에서 동일하게 적용해야 하므로
# config.CATEGORICAL_FIELDS의 "preprocess"에 등록해 한 곳에서만 관리한다.

import numpy as np
import pandas as pd


def identity(series: pd.Series) -> pd.Series:
    return series


def major_version(series: pd.Series) -> pd.Series:
    """device_os_version처럼 세부 빌드 번호까지 섞이면 vocab이 과도하게 희소해지는
    필드를 메이저 버전(첫 '.' 이전)만 남기도록 정규화. 예: "14.2.1" → "14"."""

    def _extract(v):
        if v is None:
            return v
        if isinstance(v, float) and np.isnan(v):
            return v
        s = str(v).strip()
        return s.split(".")[0] if s else v

    return series.map(_extract)
