# embedding/user_profile/model.py
#
# user_profile 필드별 Autoencoder.
# - 범주형 필드: 필드마다 독립된 nn.Embedding (임베딩 차원은 config.CATEGORICAL_FIELDS에서 지정)
# - 수치형 필드: 표준화된 스칼라를 그대로 인코더 입력에 concat
# 인코더가 뽑은 z(embed_dim)를 다시 각 필드로 복원(reconstruction)하는 손실로 학습한다.
# (레이블이 없는 상태에서 "적절한 임베딩"을 배우게 하는 self-supervised 방식)

from typing import Dict, List

import torch
import torch.nn as nn

from ..common.vocab import CategoryVocab


class UserProfileAutoencoder(nn.Module):
    def __init__(
        self,
        cat_vocabs: Dict[str, CategoryVocab],
        cat_embed_dims: Dict[str, int],
        numeric_fields: List[str],
        hidden_dim: int,
        embed_dim: int,
    ):
        super().__init__()
        self.cat_fields = list(cat_vocabs.keys())
        self.numeric_fields = list(numeric_fields)

        self.embeddings = nn.ModuleDict({
            field: nn.Embedding(len(cat_vocabs[field]), cat_embed_dims[field])
            for field in self.cat_fields
        })

        input_dim = sum(cat_embed_dims[f] for f in self.cat_fields) + len(self.numeric_fields)

        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embed_dim),
        )

        self.decoder_hidden = nn.Sequential(
            nn.Linear(embed_dim, hidden_dim),
            nn.ReLU(),
        )
        self.cat_decoders = nn.ModuleDict({
            field: nn.Linear(hidden_dim, len(cat_vocabs[field]))
            for field in self.cat_fields
        })
        self.numeric_decoder = (
            nn.Linear(hidden_dim, len(self.numeric_fields)) if self.numeric_fields else None
        )

    def encode(self, cat: Dict[str, torch.Tensor], numeric: torch.Tensor) -> torch.Tensor:
        parts = [self.embeddings[f](cat[f]) for f in self.cat_fields]
        parts.append(numeric)
        x = torch.cat(parts, dim=-1)
        return self.encoder(x)

    def forward(self, cat: Dict[str, torch.Tensor], numeric: torch.Tensor):
        z = self.encode(cat, numeric)
        h = self.decoder_hidden(z)
        cat_logits = {f: self.cat_decoders[f](h) for f in self.cat_fields}
        numeric_recon = self.numeric_decoder(h) if self.numeric_decoder is not None else None
        return z, cat_logits, numeric_recon
