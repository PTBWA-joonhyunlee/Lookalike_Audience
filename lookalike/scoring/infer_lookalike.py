# lookalike/scoring/infer_lookalike.py
#
# 학습된 lookalike 분류기로 candidate를 스코어링하고 점수 상위 후보 리스트를 뽑는다.
# 재학습 없이 저장된 분류기를 그대로 쓴다.

import os
from pathlib import Path

import numpy as np
import torch

from embedding.common.device import resolve_device
from . import config
from .dataset import load_embeddings, load_ids
from .model import LookalikeClassifier


def load_model(variant: config.Variant, device: torch.device) -> LookalikeClassifier:
    model = LookalikeClassifier(variant.embed_dim, config.HIDDEN_DIM, config.DROPOUT).to(device)
    model.load_state_dict(torch.load(variant.model_path, map_location=device))
    model.eval()
    return model


def score(
    variant: config.Variant,
    device: str = "auto",
    top_pct: float = 10.0,
    output_path: str = None,
    candidate_ids_csv=None,
    embeddings_csv=None,
    candidate_ids=None,
) -> None:
    """candidate_ids_csv/embeddings_csv를 주면 학습된 variant 모델은 그대로 재사용하되,
    다른 candidate 집단이나 다른 임베딩 CSV에 스코어링한다."""
    device = resolve_device(device)
    print(f"[INFO] variant={variant.name} device={device}")

    if embeddings_csv:
        variant = config.Variant(
            name=variant.name,
            sources=[(Path(embeddings_csv), variant.embed_cols)],
            artifact_dir=variant.artifact_dir,
            seed_ids_csv=variant.seed_ids_csv,
            pool_ids_csv=variant.pool_ids_csv,
            candidate_ids_csv=variant.candidate_ids_csv,
        )
    embeddings = load_embeddings(variant)
    if candidate_ids is None:  # set을 직접 주면(예: 기존 seed 제외 후) CSV를 읽지 않는다
        candidate_ids = load_ids(candidate_ids_csv or variant.candidate_ids_csv)
    df = embeddings[embeddings[config.ID_COL].isin(candidate_ids)].copy()
    print(f"[INFO] 후보 {len(df)}명 스코어링 (candidate 모집단 {len(candidate_ids)}명 중 임베딩 있는 대상)")

    model = load_model(variant, device)
    x = torch.from_numpy(df[variant.embed_cols].to_numpy(dtype=np.float32)).to(device)
    with torch.no_grad():
        scores = torch.sigmoid(model(x)).cpu().numpy()
    df["lookalike_score"] = scores
    df = df[[config.ID_COL, "lookalike_score"]].sort_values("lookalike_score", ascending=False)

    variant.artifact_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_path or str(variant.artifact_dir / "candidate_scores.csv")
    # top-pct 파일은 output_path와 같은 디렉터리에 둔다 — output_path를 다른 candidate
    # 집단용 경로로 override했는데 top-pct만 variant.artifact_dir(기본 경로)에 떨어지면
    # 서로 다른 candidate 집단의 결과 파일이 같은 이름으로 덮어써질 수 있다(2026-07-31
    # 실제 발생: media candidate 표본을 스코어링하다가 원래 664,684명 기준 결과를 덮어씀).
    out_dir = os.path.dirname(output_path) or str(variant.artifact_dir)
    df.to_csv(output_path, index=False)
    print(f"[INFO] 전체 스코어 저장({len(df)}명): {output_path}")

    cutoff = np.percentile(df["lookalike_score"], 100 - top_pct)
    top_df = df[df["lookalike_score"] >= cutoff]
    top_path = os.path.join(out_dir, f"candidate_scores_top{top_pct:g}pct.csv")
    top_df.to_csv(top_path, index=False)
    print(f"[INFO] 상위 {top_pct}%({len(top_df)}명, score>={cutoff:.4f}) 저장: {top_path}")
