# embedding/media_sequence/model.py
#
# SASRec: causal self-attention 기반 다음-아이템 예측 시퀀스 모델.
# BERT4Rec(양방향 마스킹) 대신 SASRec(단방향, next-item)을 먼저 구현했다 —
# vocab이 top500이라 negative sampling 없이 full softmax로 충분히 학습 가능하고,
# 마스킹 비율 등 추가 하이퍼파라미터 없이 구조가 더 단순해 검증하기 쉽다.
# 유저 임베딩은 causal 인코딩 후 마지막 "실제(non-pad)" 스텝의 hidden state를 사용한다
# (그 위치까지의 전체 방문 이력을 causal attention으로 압축한 벡터이므로).
#
# item_embedding(media) + position_embedding 외에, 이벤트 단위 보조 피처
# (content_genre/ad_type/connection_type)를 같은 embed_dim으로 만들어 같은 위치에 더한다.
# content_genre는 이벤트 1건에 여러 장르가 콤마로 붙을 수 있어 nn.EmbeddingBag(mode="mean")로
# 평균을 내고, ad_type/connection_type은 이벤트당 값이 하나뿐인 일반 nn.Embedding을 쓴다.

import math

import torch
import torch.nn as nn


class SASRec(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        max_len: int,
        embed_dim: int,
        n_heads: int,
        n_layers: int,
        ffn_dim: int,
        dropout: float,
        genre_vocab_size: int,
        ad_type_vocab_size: int,
        connection_type_vocab_size: int,
        pad_id: int = 0,
    ):
        super().__init__()
        self.pad_id = pad_id
        self.max_len = max_len
        self.embed_dim = embed_dim

        self.item_embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=pad_id)
        self.position_embedding = nn.Embedding(max_len, embed_dim)
        self.genre_embedding = nn.EmbeddingBag(genre_vocab_size, embed_dim, mode="mean", padding_idx=pad_id)
        self.ad_type_embedding = nn.Embedding(ad_type_vocab_size, embed_dim, padding_idx=pad_id)
        self.connection_type_embedding = nn.Embedding(connection_type_vocab_size, embed_dim, padding_idx=pad_id)
        self.embed_dropout = nn.Dropout(dropout)
        self.embed_norm = nn.LayerNorm(embed_dim)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim,
            nhead=n_heads,
            dim_feedforward=ffn_dim,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.output_norm = nn.LayerNorm(embed_dim)

        # 출력 projection은 item_embedding과 weight tying (SASRec 원 논문 방식, 파라미터 절약)
        self.out_bias = nn.Parameter(torch.zeros(vocab_size))

    def _causal_mask(self, seq_len: int, device: torch.device) -> torch.Tensor:
        return torch.triu(torch.full((seq_len, seq_len), float("-inf"), device=device), diagonal=1)

    def encode(
        self,
        input_ids: torch.Tensor,
        genre_ids: torch.Tensor,
        ad_type_ids: torch.Tensor,
        connection_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        """input_ids: (B, L), genre_ids: (B, L, G), ad_type_ids/connection_type_ids: (B, L)
        -> hidden states (B, L, D)."""
        batch_size, seq_len = input_ids.shape
        positions = torch.arange(seq_len, device=input_ids.device).unsqueeze(0).expand(batch_size, seq_len)

        x = self.item_embedding(input_ids) * math.sqrt(self.embed_dim)
        x = x + self.position_embedding(positions)

        # EmbeddingBag은 2D 입력만 받으므로 (B, L, G) -> (B*L, G)로 펼쳐 평균을 낸 뒤 되돌린다.
        genre_flat = genre_ids.reshape(-1, genre_ids.size(-1))
        genre_emb = self.genre_embedding(genre_flat).reshape(batch_size, seq_len, self.embed_dim)
        x = x + genre_emb

        x = x + self.ad_type_embedding(ad_type_ids)
        x = x + self.connection_type_embedding(connection_type_ids)

        x = self.embed_dropout(self.embed_norm(x))

        # mask/src_key_padding_mask는 같은 타입(둘 다 additive float)으로 맞춘다 —
        # bool과 float를 섞어 쓰면 torch가 deprecation 경고를 낸다.
        causal_mask = self._causal_mask(seq_len, input_ids.device)
        pad_mask = torch.zeros(batch_size, seq_len, dtype=x.dtype, device=x.device)
        pad_mask.masked_fill_(input_ids.eq(self.pad_id), float("-inf"))

        hidden = self.encoder(x, mask=causal_mask, src_key_padding_mask=pad_mask)
        return self.output_norm(hidden)

    def logits(self, hidden: torch.Tensor) -> torch.Tensor:
        """hidden: (B, L, D) -> (B, L, vocab_size)."""
        return hidden @ self.item_embedding.weight.t() + self.out_bias

    def forward(
        self,
        input_ids: torch.Tensor,
        genre_ids: torch.Tensor,
        ad_type_ids: torch.Tensor,
        connection_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        return self.logits(self.encode(input_ids, genre_ids, ad_type_ids, connection_type_ids))

    def pooled_embedding(
        self,
        input_ids: torch.Tensor,
        lengths: torch.Tensor,
        genre_ids: torch.Tensor,
        ad_type_ids: torch.Tensor,
        connection_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        """유저 1명당 임베딩 = 마지막 실제(non-pad) 스텝 위치의 hidden state."""
        hidden = self.encode(input_ids, genre_ids, ad_type_ids, connection_type_ids)  # (B, L, D)
        last_idx = (lengths - 1).clamp(min=0)
        batch_idx = torch.arange(hidden.size(0), device=hidden.device)
        return hidden[batch_idx, last_idx]  # (B, D)
