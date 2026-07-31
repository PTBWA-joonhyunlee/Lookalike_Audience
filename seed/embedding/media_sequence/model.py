# seed/embedding/media_sequence/model.py
#
# SASRec: causal self-attention 기반 다음-아이템 예측 시퀀스 모델(옛 addi 트랙
# embedding/media_sequence/model.py를 propfit 스키마로 이식).
# BERT4Rec(양방향 마스킹) 대신 SASRec(단방향, next-item)을 쓰는 이유·유저 임베딩을
# "마지막 실제(non-pad) 스텝의 hidden state"로 뽑는 이유는 addi 시절과 동일(원 설계
# 그대로 유지) — 바뀐 건 보조 피처 하나뿐이다: addi는 content_genre(콤마 구분 다중
# 장르)가 있어 nn.EmbeddingBag으로 평균을 냈지만, propfit 02_user_media.sql은
# content_genre가 비어 있는 대신 inventory_type(app/site, 이벤트당 값 하나)을 준다 —
# ad_type/connection_type과 똑같이 단일값 nn.Embedding으로 다룬다(EmbeddingBag 불필요).

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
        inventory_type_vocab_size: int,
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
        self.inventory_type_embedding = nn.Embedding(inventory_type_vocab_size, embed_dim, padding_idx=pad_id)
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
        inventory_type_ids: torch.Tensor,
        ad_type_ids: torch.Tensor,
        connection_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        """input_ids/inventory_type_ids/ad_type_ids/connection_type_ids: (B, L) -> hidden states (B, L, D)."""
        batch_size, seq_len = input_ids.shape
        positions = torch.arange(seq_len, device=input_ids.device).unsqueeze(0).expand(batch_size, seq_len)

        x = self.item_embedding(input_ids) * math.sqrt(self.embed_dim)
        x = x + self.position_embedding(positions)
        x = x + self.inventory_type_embedding(inventory_type_ids)
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
        inventory_type_ids: torch.Tensor,
        ad_type_ids: torch.Tensor,
        connection_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        return self.logits(self.encode(input_ids, inventory_type_ids, ad_type_ids, connection_type_ids))

    def pooled_embedding(
        self,
        input_ids: torch.Tensor,
        lengths: torch.Tensor,
        inventory_type_ids: torch.Tensor,
        ad_type_ids: torch.Tensor,
        connection_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        """유저 1명당 임베딩 = 마지막 실제(non-pad) 스텝 위치의 hidden state."""
        hidden = self.encode(input_ids, inventory_type_ids, ad_type_ids, connection_type_ids)  # (B, L, D)
        last_idx = (lengths - 1).clamp(min=0)
        batch_idx = torch.arange(hidden.size(0), device=hidden.device)
        return hidden[batch_idx, last_idx]  # (B, D)
