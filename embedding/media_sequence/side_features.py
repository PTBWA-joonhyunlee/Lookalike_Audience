# embedding/media_sequence/side_features.py
#
# content_genre(콤마 구분 다중 장르) / ad_type / connection_type 보조 피처의 vocab
# 적합·저장·로드를 한 곳에 모은다. media(주 아이템) 임베딩에 "더해지는" 보조 신호로
# model.SASRec에 들어간다 — 자세한 결합 방식은 model.py, 전체 설계는
# docs/embedding-spec-top500-media-visit.md 참고.

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

import numpy as np
import pandas as pd

from ..common.vocab import CategoryVocab
from . import config


def split_genres(value) -> List[str]:
    """content_genre의 콤마 구분 다중 장르 문자열 -> 개별 장르 토큰 리스트.
    결측/빈 문자열은 빈 리스트(= 해당 이벤트에 장르 신호 없음)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    s = str(value).strip()
    if not s:
        return []
    return [g.strip() for g in s.split(config.GENRE_DELIM) if g.strip()]


@dataclass
class SideFeatureVocabs:
    genre: CategoryVocab
    ad_type: CategoryVocab
    connection_type: CategoryVocab

    @classmethod
    def fit(cls, df: pd.DataFrame) -> "SideFeatureVocabs":
        genre_tokens = (token for value in df[config.CONTENT_GENRE_COL] for token in split_genres(value))
        genre = CategoryVocab.build(
            genre_tokens, min_freq=config.SIDE_FEATURE_MIN_FREQ, max_size=config.CONTENT_GENRE_MAX_VOCAB_SIZE
        )
        ad_type = CategoryVocab.build(
            df[config.AD_TYPE_COL].dropna(),
            min_freq=config.SIDE_FEATURE_MIN_FREQ,
            max_size=config.AD_TYPE_MAX_VOCAB_SIZE,
        )
        connection_type = CategoryVocab.build(
            df[config.CONNECTION_TYPE_COL].dropna(),
            min_freq=config.SIDE_FEATURE_MIN_FREQ,
            max_size=config.CONNECTION_TYPE_MAX_VOCAB_SIZE,
        )
        return cls(genre=genre, ad_type=ad_type, connection_type=connection_type)

    def save(self, dir_path: Union[str, Path]) -> None:
        self.genre.save(os.path.join(str(dir_path), "vocab_content_genre.json"))
        self.ad_type.save(os.path.join(str(dir_path), "vocab_ad_type.json"))
        self.connection_type.save(os.path.join(str(dir_path), "vocab_connection_type.json"))

    @classmethod
    def load(cls, dir_path: Union[str, Path]) -> "SideFeatureVocabs":
        return cls(
            genre=CategoryVocab.load(os.path.join(str(dir_path), "vocab_content_genre.json")),
            ad_type=CategoryVocab.load(os.path.join(str(dir_path), "vocab_ad_type.json")),
            connection_type=CategoryVocab.load(os.path.join(str(dir_path), "vocab_connection_type.json")),
        )
