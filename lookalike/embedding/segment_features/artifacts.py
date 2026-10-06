# lookalike/embedding/segment_features/artifacts.py
#
# 오토인코더 버전(ae_version) 하나 = 디렉터리 하나. 그 안에 이 버전으로 임베딩을 뽑는 데 필요한 것이
# 전부 들어 있다(다른 버전/전역 config에 의존하지 않는다):
#   model.pt                 학습된 가중치
#   age_bracket_vocab.json   학습 데이터로 만든 연령대 vocab(인덱스 매핑이 모델마다 다르다)
#   segment_bert_lookup.npz  segment_id -> 768dim 벡터(taxonomy 기준, 데이터와 무관)
#   config.json              모델 구조 + 학습 설정 + 학습 결과 + 출처(pool/git commit)
#
# 옛 버전(legacy)은 data/models/segment_features/ 에 같은 파일명으로 있고 config.json이 없다 —
# 그 경우 embedding/segment_features/config.py의 기본값이 곧 그 모델의 구조다.

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict

import torch

from ..common.vocab import CategoryVocab
from . import config
from .bert_lookup import SegmentEmbeddingLookup
from .model import SegmentFeaturesAutoencoder

MODEL_FILE = "model.pt"
AGE_VOCAB_FILE = "age_bracket_vocab.json"
BERT_LOOKUP_FILE = "segment_bert_lookup.npz"
CONFIG_FILE = "config.json"


@dataclass
class ModelSpec:
    """모델 구조 하이퍼파라미터 — 가중치를 다시 불러올 때 같은 구조를 만들기 위해 config.json에 저장한다."""
    age_embed_dim: int = config.AGE_EMBED_DIM
    proj_dims: Dict[str, int] = field(default_factory=lambda: dict(config.PROJ_DIMS))
    hidden_dim: int = config.HIDDEN_DIM
    z_dim: int = config.EMBED_DIM
    freeze_bert_lookup: bool = config.FREEZE_BERT_LOOKUP

    def to_dict(self) -> dict:
        return asdict(self)


def load_model_spec(ae_dir) -> ModelSpec:
    path = Path(ae_dir) / CONFIG_FILE
    if not path.exists():
        return ModelSpec()
    data = json.loads(path.read_text(encoding="utf-8")).get("model")
    return ModelSpec(**data) if data else ModelSpec()


def load_age_vocab(ae_dir) -> CategoryVocab:
    return CategoryVocab.load(Path(ae_dir) / AGE_VOCAB_FILE)


def load_bert_lookup(ae_dir) -> SegmentEmbeddingLookup:
    return SegmentEmbeddingLookup.load(Path(ae_dir) / BERT_LOOKUP_FILE)


def build_model(ae_dir, spec: ModelSpec = None) -> SegmentFeaturesAutoencoder:
    """ae_dir의 vocab/lookup으로 (가중치 로드 전) 모델을 만든다."""
    spec = spec or load_model_spec(ae_dir)
    lookup = load_bert_lookup(ae_dir)
    return SegmentFeaturesAutoencoder(
        age_vocab_size=len(load_age_vocab(ae_dir)),
        bert_lookup_vectors=torch.tensor(lookup.vectors, dtype=torch.float32),
        age_embed_dim=spec.age_embed_dim,
        proj_dims=spec.proj_dims,
        hidden_dim=spec.hidden_dim,
        z_dim=spec.z_dim,
        freeze_bert_lookup=spec.freeze_bert_lookup,
    )


def load_trained_model(ae_dir, device) -> SegmentFeaturesAutoencoder:
    model = build_model(ae_dir).to(device)
    model.load_state_dict(torch.load(Path(ae_dir) / MODEL_FILE, map_location=device))
    model.eval()
    return model


def file_sha256(path, length: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()[:length]


def describe(ae_dir, ae_version: str) -> dict:
    """run.json/model config에 남길 "이 실행이 어떤 임베딩 모델을 썼는가" 요약."""
    ae_dir = Path(ae_dir)
    info = {"ae_version": ae_version, "ae_dir": str(ae_dir), "model_sha256": file_sha256(ae_dir / MODEL_FILE)}
    cfg_path = ae_dir / CONFIG_FILE
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        info["trained_at"] = cfg.get("trained_at")
        info["trained_on_pool"] = (cfg.get("pool") or {}).get("pool_id")
        info["model"] = cfg.get("model")
        info["train"] = {k: v for k, v in (cfg.get("train") or {}).items() if k != "history"}
        info["git_commit"] = cfg.get("git_commit")
    else:
        info["note"] = "config.json 없음(legacy 모델) — 구조는 embedding/segment_features/config.py 기본값"
        info["model"] = ModelSpec().to_dict()
    return info
