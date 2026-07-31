# seed/scoring/infer_lookalike.py
#
# 학습된 lookalike 분류기로 6월 candidate(07a/07b/07c_candidate_*.csv 대상, 66만 명)를
# 스코어링하고, 점수 상위 후보 리스트를 뽑는다. addi 트랙의
# scoring/infer_supervised_lookalike.py에 해당하는 자리 — 재학습 없이 저장된 분류기를
# 그대로 쓴다.
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m scoring.infer_lookalike [--top-pct 10]

import argparse

import numpy as np
import pandas as pd
import torch

from embedding.common.device import resolve_device
from . import config
from .dataset import load_embeddings, load_ids
from .model import LookalikeClassifier


def load_model(device: torch.device) -> LookalikeClassifier:
    model = LookalikeClassifier(config.EMBED_DIM, config.HIDDEN_DIM, config.DROPOUT).to(device)
    model.load_state_dict(torch.load(config.MODEL_PATH, map_location=device))
    model.eval()
    return model


def score(device: str = "auto", top_pct: float = 10.0, output_path: str = None) -> None:
    device = resolve_device(device)
    print(f"[INFO] device={device}")

    embeddings = load_embeddings()
    candidate_ids = load_ids(config.CANDIDATE_IDS_CSV)
    df = embeddings[embeddings[config.ID_COL].isin(candidate_ids)].copy()
    print(f"[INFO] 후보 {len(df)}명 스코어링 (candidate 모집단 {len(candidate_ids)}명 중 임베딩 있는 대상)")

    model = load_model(device)
    x = torch.from_numpy(df[config.EMBED_COLS].to_numpy(dtype=np.float32)).to(device)
    with torch.no_grad():
        scores = torch.sigmoid(model(x)).cpu().numpy()
    df["lookalike_score"] = scores
    df = df[[config.ID_COL, "lookalike_score"]].sort_values("lookalike_score", ascending=False)

    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = output_path or str(config.ARTIFACT_DIR / "candidate_scores.csv")
    df.to_csv(output_path, index=False)
    print(f"[INFO] 전체 스코어 저장({len(df)}명): {output_path}")

    cutoff = np.percentile(df["lookalike_score"], 100 - top_pct)
    top_df = df[df["lookalike_score"] >= cutoff]
    top_path = str(config.ARTIFACT_DIR / f"candidate_scores_top{top_pct:g}pct.csv")
    top_df.to_csv(top_path, index=False)
    print(f"[INFO] 상위 {top_pct}%({len(top_df)}명, score>={cutoff:.4f}) 저장: {top_path}")


def main():
    parser = argparse.ArgumentParser(description="candidate lookalike 스코어링 + 상위 후보 추출")
    parser.add_argument("--top-pct", type=float, default=10.0, help="상위 N%% 후보 리스트도 같이 저장")
    parser.add_argument("--output", help="전체 스코어 CSV 저장 경로")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    score(device=args.device, top_pct=args.top_pct, output_path=args.output)


if __name__ == "__main__":
    main()
