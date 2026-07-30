# seed/embedding/segment_features/model.py
#
# segment_features Autoencoder — seed/docs/model_architecture.md 설계.
# 시퀀스가 아니라 유저 1명당 스냅샷 필드들이라 Autoencoder 구조를 쓴다.
#
# - gender_score: 스칼라, 그대로 concat
# - age_bracket_idx: nn.Embedding(age_vocab_size, AGE_EMBED_DIM)
# - residence/product_interest/content_interest/etc_segment: 하나의 공유 nn.EmbeddingBag
#   (segment_bert_lookup.npz로 초기화)에 그룹별로 각각 호출해 768dim으로 풀링한 뒤,
#   그룹별 Linear 투영(PROJ_DIMS)으로 차원을 줄여서 concat한다 — 768dim을 그대로 concat하면
#   나머지 필드(1~8dim)를 압도해버리기 때문.
# - 디코더는 학습에만 쓰고 버린다(인코더 출력 z만 임베딩으로 남김). residence/product/
#   content/etc 그룹은 원본 768dim이 아니라 인코더가 만든 projection 출력을 복원 타깃으로
#   삼는다 — 768dim 자체를 타깃으로 쓰면 손실이 그 큰 차원에 지배되기 때문(문서 참고).
#   학습 스크립트는 이 타깃에 .detach()를 적용해 두 branch가 서로를 향해 붕괴하는 것을 막는다.

from typing import Dict

import torch
import torch.nn as nn

POOLED_GROUPS = ("residence", "product_interest", "content_interest", "etc_segment")


class SegmentFeaturesAutoencoder(nn.Module):
    def __init__(
        self,
        age_vocab_size: int,
        bert_lookup_vectors: torch.Tensor,   # (vocab+1, 768), index 0 = padding(0벡터)
        age_embed_dim: int,
        proj_dims: Dict[str, int],
        hidden_dim: int,
        z_dim: int,
        freeze_bert_lookup: bool = False,
    ):
        super().__init__()
        self.proj_dims = dict(proj_dims)
        bert_dim = bert_lookup_vectors.shape[1]

        self.age_embedding = nn.Embedding(age_vocab_size, age_embed_dim, padding_idx=0)
        self.shared_bag = nn.EmbeddingBag.from_pretrained(
            bert_lookup_vectors, freeze=freeze_bert_lookup, mode="mean", padding_idx=0
        )
        self.projections = nn.ModuleDict({
            g: nn.Linear(bert_dim, proj_dims[g]) for g in POOLED_GROUPS
        })

        input_dim = 1 + age_embed_dim + sum(proj_dims[g] for g in POOLED_GROUPS)
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, z_dim),
        )

        self.decoder_hidden = nn.Sequential(
            nn.Linear(z_dim, hidden_dim),
            nn.ReLU(),
        )
        self.gender_head = nn.Linear(hidden_dim, 1)
        self.age_head = nn.Linear(hidden_dim, age_vocab_size)
        self.group_heads = nn.ModuleDict({
            g: nn.Linear(hidden_dim, proj_dims[g]) for g in POOLED_GROUPS
        })

    def encode(self, batch: Dict[str, torch.Tensor]):
        """batch: gender_score(B,), age_bracket_idx(B,), {group}_idx(B, max_len) 텐서 딕셔너리.
        -> z(B, z_dim), group_projections({group: (B, proj_dim)}) — 후자는 디코더 복원 타깃."""
        parts = [batch["gender_score"].unsqueeze(-1), self.age_embedding(batch["age_bracket_idx"])]
        group_projections = {}
        for g in POOLED_GROUPS:
            pooled = self.shared_bag(batch[f"{g}_idx"])          # (B, 768)
            proj = self.projections[g](pooled)                    # (B, proj_dim)
            group_projections[g] = proj
            parts.append(proj)
        z = self.encoder(torch.cat(parts, dim=-1))
        return z, group_projections

    def forward(self, batch: Dict[str, torch.Tensor]):
        z, group_projections = self.encode(batch)
        h = self.decoder_hidden(z)
        gender_pred = self.gender_head(h).squeeze(-1)
        age_logits = self.age_head(h)
        group_recons = {g: self.group_heads[g](h) for g in POOLED_GROUPS}
        return z, gender_pred, age_logits, group_projections, group_recons
