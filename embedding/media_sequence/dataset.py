# embedding/media_sequence/dataset.py

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from ..common.vocab import CategoryVocab, NA_TOKEN
from .side_features import SideFeatureVocabs, split_genres

IGNORE_INDEX = -100  # nn.CrossEntropyLoss 기본 ignore_index와 맞춤 (target 패딩용)


def build_sequences(
    df: pd.DataFrame, id_col: str, media_col: str, ts_col: str, extra_cols: Tuple[str, ...] = ()
) -> Dict[str, Dict[str, list]]:
    """이벤트 그레인 DataFrame(req_user_id, media, ts, ...) -> req_user_id별 시간순
    {media_col: [...], extra_col: [...], ...} 딕셔너리. 01_top500_media_visit.sql이 이미
    "단기 재방문"을 걸러낸 상태로 내려주므로 여기서는 정렬 + 묶기만 한다. extra_cols는 media와
    같은 이벤트 그레인이라 정렬 순서가 그대로 맞춰진다(같은 인덱스 = 같은 이벤트)."""
    cols = [id_col, media_col, ts_col, *extra_cols]
    sub = df[cols].dropna(subset=[media_col]).copy()
    sub[ts_col] = pd.to_datetime(sub[ts_col])
    sub = sub.sort_values([id_col, ts_col])
    value_cols = [media_col, *extra_cols]
    return {uid: {c: g[c].tolist() for c in value_cols} for uid, g in sub.groupby(id_col)}


def encode_padded(
    tokens: List, vocab: CategoryVocab, max_len: int, pad_id: int
) -> Tuple[np.ndarray, int]:
    """단일 범주형 토큰 리스트 -> (max_len 길이로 우측 패딩된 id 배열, 실제 길이). 뒤쪽(최근) max_len개만 사용."""
    tokens = tokens[-max_len:]
    ids = vocab.encode_series(pd.Series(tokens)) if tokens else np.zeros(0, dtype=np.int64)
    length = len(ids)
    if length < max_len:
        ids = np.concatenate([ids, np.full(max_len - length, pad_id, dtype=np.int64)])
    return ids, length


def encode_padded_genres(
    genre_values: List, vocab: CategoryVocab, max_len: int, max_genres: int
) -> np.ndarray:
    """이벤트별 content_genre 원본 값(콤마 구분 문자열) 리스트 -> (max_len, max_genres) id 배열.
    pad id는 항상 0(<NA>)이라, 시간축 패딩(이벤트가 없음)과 장르축 패딩(그 이벤트에 장르가
    max_genres보다 적음)을 같은 값으로 둬도 안전하다 — 둘 다 model.SASRec의
    genre_embedding(nn.EmbeddingBag, padding_idx=0)에서 평균 계산 대상에서 제외된다."""
    genre_values = genre_values[-max_len:]
    rows = np.zeros((max_len, max_genres), dtype=np.int64)
    for i, value in enumerate(genre_values):
        tokens = split_genres(value)[:max_genres]
        if tokens:
            rows[i, : len(tokens)] = [vocab.encode(t) for t in tokens]
    return rows


class MediaSequenceDataset(Dataset):
    """SASRec 다음-아이템 예측 학습용. 시퀀스 길이가 min_len 미만이면(학습 신호가 너무 약해)
    학습 대상에서 제외한다 (임베딩 추출은 MediaSequenceInferenceDataset이 별도로 처리)."""

    def __init__(
        self,
        df: pd.DataFrame,
        vocab: CategoryVocab,
        max_len: int,
        id_col: str,
        media_col: str,
        ts_col: str,
        genre_col: str,
        ad_type_col: str,
        connection_type_col: str,
        side_vocabs: SideFeatureVocabs,
        max_genres: int,
        min_len: int = 2,
    ):
        self.max_len = max_len
        self.pad_id = vocab.token_to_id[NA_TOKEN]

        self.ids: List[str] = []
        self.inputs: List[np.ndarray] = []
        self.targets: List[np.ndarray] = []
        self.lengths: List[int] = []
        self.genres: List[np.ndarray] = []
        self.ad_types: List[np.ndarray] = []
        self.connection_types: List[np.ndarray] = []
        self.skipped = 0

        ad_type_pad = side_vocabs.ad_type.token_to_id[NA_TOKEN]
        connection_type_pad = side_vocabs.connection_type.token_to_id[NA_TOKEN]

        sequences = build_sequences(df, id_col, media_col, ts_col, (genre_col, ad_type_col, connection_type_col))
        for uid, seqs in sequences.items():
            tokens = seqs[media_col]
            if len(tokens) < min_len:
                self.skipped += 1
                continue

            window = tokens[-(max_len + 1):]
            inp_tokens, tgt_tokens = window[:-1], window[1:]

            inp_ids, length = encode_padded(inp_tokens, vocab, max_len, self.pad_id)
            tgt_ids_raw = vocab.encode_series(pd.Series(tgt_tokens))
            tgt_ids = np.full(max_len, IGNORE_INDEX, dtype=np.int64)
            tgt_ids[: len(tgt_ids_raw)] = tgt_ids_raw

            # 보조 피처는 input 위치(=현재 이벤트, window[:-1])에만 맞춰 인코딩한다.
            # 다음 아이템 예측 target(다음 이벤트) 쪽에는 쓰지 않는다.
            genre_window = seqs[genre_col][-(max_len + 1):][:-1]
            genre_ids = encode_padded_genres(genre_window, side_vocabs.genre, max_len, max_genres)

            ad_type_window = seqs[ad_type_col][-(max_len + 1):][:-1]
            ad_type_ids, _ = encode_padded(ad_type_window, side_vocabs.ad_type, max_len, ad_type_pad)

            conn_window = seqs[connection_type_col][-(max_len + 1):][:-1]
            conn_ids, _ = encode_padded(conn_window, side_vocabs.connection_type, max_len, connection_type_pad)

            self.ids.append(str(uid))
            self.inputs.append(inp_ids)
            self.targets.append(tgt_ids)
            self.lengths.append(length)
            self.genres.append(genre_ids)
            self.ad_types.append(ad_type_ids)
            self.connection_types.append(conn_ids)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return (
            self.ids[idx],
            torch.tensor(self.inputs[idx], dtype=torch.long),
            torch.tensor(self.targets[idx], dtype=torch.long),
            self.lengths[idx],
            torch.tensor(self.genres[idx], dtype=torch.long),
            torch.tensor(self.ad_types[idx], dtype=torch.long),
            torch.tensor(self.connection_types[idx], dtype=torch.long),
        )


class MediaSequenceInferenceDataset(Dataset):
    """학습 여부와 무관하게 모든 유저의 임베딩을 뽑기 위한 추론 전용 Dataset
    (다음 아이템 target이 필요 없어 시퀀스 길이 1인 유저도 그대로 포함)."""

    def __init__(
        self,
        df: pd.DataFrame,
        vocab: CategoryVocab,
        max_len: int,
        id_col: str,
        media_col: str,
        ts_col: str,
        genre_col: str,
        ad_type_col: str,
        connection_type_col: str,
        side_vocabs: SideFeatureVocabs,
        max_genres: int,
    ):
        self.pad_id = vocab.token_to_id[NA_TOKEN]

        self.ids: List[str] = []
        self.inputs: List[np.ndarray] = []
        self.lengths: List[int] = []
        self.genres: List[np.ndarray] = []
        self.ad_types: List[np.ndarray] = []
        self.connection_types: List[np.ndarray] = []

        ad_type_pad = side_vocabs.ad_type.token_to_id[NA_TOKEN]
        connection_type_pad = side_vocabs.connection_type.token_to_id[NA_TOKEN]

        sequences = build_sequences(df, id_col, media_col, ts_col, (genre_col, ad_type_col, connection_type_col))
        for uid, seqs in sequences.items():
            tokens = seqs[media_col]
            ids, length = encode_padded(tokens, vocab, max_len, self.pad_id)
            genre_ids = encode_padded_genres(seqs[genre_col], side_vocabs.genre, max_len, max_genres)
            ad_type_ids, _ = encode_padded(seqs[ad_type_col], side_vocabs.ad_type, max_len, ad_type_pad)
            conn_ids, _ = encode_padded(
                seqs[connection_type_col], side_vocabs.connection_type, max_len, connection_type_pad
            )

            self.ids.append(str(uid))
            self.inputs.append(ids)
            # 방어적 처리: 시퀀스가 완전히 비어 있어도(길이 0) 인덱싱이 가능하도록 최소 1 보장.
            self.lengths.append(max(length, 1))
            self.genres.append(genre_ids)
            self.ad_types.append(ad_type_ids)
            self.connection_types.append(conn_ids)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return (
            self.ids[idx],
            torch.tensor(self.inputs[idx], dtype=torch.long),
            self.lengths[idx],
            torch.tensor(self.genres[idx], dtype=torch.long),
            torch.tensor(self.ad_types[idx], dtype=torch.long),
            torch.tensor(self.connection_types[idx], dtype=torch.long),
        )
