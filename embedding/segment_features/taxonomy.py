# embedding/segment_features/taxonomy.py
#
# 세그먼트_카테고리.csv(로컬 참조 파일, Athena 테이블 아님)에서 segment_id -> 카테고리
# 경로 텍스트를 만든다. 이 텍스트가 BERT 문장임베딩의 입력이 된다.

import pandas as pd

from . import config

_DEPTH_COLS = [
    "세그먼트 카테고리 Depth 1",
    "세그먼트 카테고리 Depth 2",
    "세그먼트 카테고리 Depth 3",
    "세그먼트 이름",
]


def load_segment_texts(csv_path=None) -> dict:
    """segment_id(str) -> "Depth1>Depth2>Depth3>세그먼트이름" 텍스트. 빈 depth는 건너뛴다."""
    path = csv_path or config.SEGMENT_CATEGORY_CSV
    df = pd.read_csv(path, dtype={"세그먼트 ID": str})

    texts = {}
    for _, row in df.iterrows():
        parts = [str(row[c]).strip() for c in _DEPTH_COLS if pd.notna(row[c]) and str(row[c]).strip()]
        texts[row["세그먼트 ID"]] = ">".join(parts)
    return texts
