# seed/embedding/segment_features/build_features.py
#
# seed/queries/lib/11_user_embedding_features.sql 출력 CSV -> 학습용 피처 배열.
#   gender_score      : SQL에서 이미 계산된 스칼라, 그대로 통과
#   age_bracket_idx   : CategoryVocab 원핫 인덱스(0=<NA>, 1=<UNK>=모름, 2~=실제 값)
#   residence_idx     : segment_id 인덱스 배열(패딩=0), 하나의 bag
#   product/content/etc_idx : 같은 lookup(segment_bert_lookup.npz) 공유, 그룹별로 각각 배열
#
# 여기서는 mean pooling을 하지 않는다 — 디바이스 x 그룹마다 768dim 벡터를 저장하면 1% 표본
# (53만 명)만으로도 6GB를 넘어(4그룹 x 768 x float32) 전체 모집단(5,300만 명)에서는 저장이
# 불가능하다. 대신 인덱스 배열만 저장하고(그룹별 max_len, config.POOLED_MAX_LEN), 실제
# mean pooling은 학습 시 nn.EmbeddingBag.from_pretrained(lookup.vectors, padding_idx=0)이
# 배치 단위로 계산한다.

from glob import glob

import numpy as np
import pandas as pd

from . import config
from .bert_lookup import SegmentEmbeddingLookup
from .pooling import encode_padded_ids_column
from ..common.vocab import CategoryVocab


def _first_id(id_string):
    if not isinstance(id_string, str) or not id_string:
        return None
    return id_string.split(";")[0]


def load_raw() -> pd.DataFrame:
    paths = sorted(glob(str(config.DATA_DIR / config.DATA_GLOB)))
    if not paths:
        raise FileNotFoundError(f"no CSV matching {config.DATA_GLOB} under {config.DATA_DIR}")
    return pd.concat([pd.read_csv(p, dtype=str) for p in paths], ignore_index=True)


def build(df: pd.DataFrame, lookup: SegmentEmbeddingLookup, age_vocab: CategoryVocab = None):
    age_primary = df[config.AGE_BRACKET_ID_COL].map(_first_id)
    if age_vocab is None:
        age_vocab = CategoryVocab.build(age_primary)

    features = {
        config.ID_COL: df[config.ID_COL].to_numpy(),
        "gender_score": df[config.GENDER_SCORE_COL].astype(np.float32).to_numpy(),
        "age_bracket_idx": age_vocab.encode_series(age_primary),
    }
    for name, col in config.POOLED_ID_COLUMNS.items():
        features[f"{name}_idx"] = encode_padded_ids_column(df[col], lookup, config.POOLED_MAX_LEN[name])

    return features, age_vocab


def main():
    df = load_raw()
    lookup = SegmentEmbeddingLookup.build_or_load()
    features, age_vocab = build(df, lookup)

    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    age_vocab.save(config.AGE_VOCAB_PATH)
    np.savez(config.ARTIFACT_DIR / "segment_features.npz", **features)
    print(f"{len(df)} devices -> {config.ARTIFACT_DIR / 'segment_features.npz'}")


if __name__ == "__main__":
    main()
