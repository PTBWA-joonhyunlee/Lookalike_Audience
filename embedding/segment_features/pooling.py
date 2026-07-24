# embedding/segment_features/pooling.py
#
# 세미콜론 구분 segment_id 문자열 -> 고정 길이 인덱스 배열(패딩 id=0). 실제 mean pooling은
# 여기서 하지 않는다 — 학습 시 nn.EmbeddingBag(padding_idx=0, mode="mean")이 배치 단위로
# 계산한다(embedding/media_sequence.encode_padded_genres와 동일 패턴). 초과분(max_len보다
# 많은 태그)은 뒤쪽 값 우선으로 자른다.

import numpy as np

from .bert_lookup import SegmentEmbeddingLookup


def encode_padded_ids(id_string, lookup: SegmentEmbeddingLookup, max_len: int) -> np.ndarray:
    row = np.zeros(max_len, dtype=np.int64)
    if not isinstance(id_string, str) or not id_string:
        return row

    ids = id_string.split(";")[-max_len:]
    row[: len(ids)] = [lookup.index_of(i) for i in ids]
    return row


def encode_padded_ids_column(series, lookup: SegmentEmbeddingLookup, max_len: int) -> np.ndarray:
    return np.stack([encode_padded_ids(v, lookup, max_len) for v in series])
