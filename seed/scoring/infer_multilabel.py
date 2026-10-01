# seed/scoring/infer_multilabel.py
#
# train_multilabel.py로 학습한 멀티헤드 분류기로 candidate를 스코어링하고, 라벨별 상위 N%를
# 뽑는다. 결과의 모든 행에 라벨별 점수가 같이 붙는다:
#   - score_<key>: 라벨별 sigmoid 점수. pos_weight로 학습해 보정되지 않은 값이라 라벨 안에서의
#     순위에만 의미가 있다(라벨 간 원점수 비교 X).
#   - pct_<key>:   candidate 전체 안에서 그 라벨 점수의 백분위(0~100, 높을수록 유사) — 라벨 간
#     비교는 이걸로 한다.
#   - top_label:   pct가 가장 높은 라벨.
#
# 산출물(artifact_dir 또는 --output-dir):
#   candidate_scores.csv              candidate 전체 × 라벨별 score/pct
#   candidate_scores_top<N>pct.csv    어느 라벨이든 상위 N%에 든 유저(합집합) + in_top_<key>
#                                      플래그 + selected_labels("gomsin;enlistee" 형태)
#   top<N>pct_<key>.csv               라벨별 상위 N% (그 라벨 점수 내림차순, 다른 라벨 점수도 포함)
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m scoring.infer_multilabel --variant military --top-pct 10

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from embedding.common.device import resolve_device
from . import config
from .dataset import load_embeddings, load_ids
from .model import MultiHeadLookalikeClassifier


def load_model(variant: config.MultiLabelVariant, device: torch.device):
    meta = json.loads(variant.labels_path.read_text(encoding="utf-8"))
    keys = [lb["key"] for lb in meta["labels"]]
    if keys != variant.label_keys:
        raise ValueError(f"저장된 모델의 라벨 순서 {keys}가 config의 {variant.label_keys}와 다릅니다 — 재학습할 것")
    model = MultiHeadLookalikeClassifier(len(meta["embed_cols"]), meta["hidden_dim"], len(keys), config.DROPOUT).to(device)
    model.load_state_dict(torch.load(variant.model_path, map_location=device))
    model.eval()
    return model, meta


def score(
    variant: config.MultiLabelVariant,
    device: str = "auto",
    top_pct: float = 10.0,
    candidate_ids_csv=None,
    output_dir=None,
    batch_size: int = 65536,
) -> pd.DataFrame:
    device = resolve_device(device)
    keys = variant.label_keys
    print(f"[INFO] variant={variant.name} labels={keys} device={device}")

    embeddings = load_embeddings(variant)
    candidate_ids = load_ids(candidate_ids_csv or variant.candidate_ids_csv)
    df = embeddings[embeddings[config.ID_COL].isin(candidate_ids)].reset_index(drop=True)
    print(f"[INFO] 후보 {len(df)}명 스코어링 (candidate 모집단 {len(candidate_ids)}명 중 임베딩 있는 대상)")

    model, _ = load_model(variant, device)
    x_all = df[variant.embed_cols].to_numpy(dtype=np.float32)
    chunks = []
    with torch.no_grad():
        for i in range(0, len(x_all), batch_size):
            x = torch.from_numpy(x_all[i:i + batch_size]).to(device)
            chunks.append(torch.sigmoid(model(x)).cpu().numpy())
    scores = np.concatenate(chunks) if chunks else np.empty((0, len(keys)), dtype=np.float32)

    out = pd.DataFrame({config.ID_COL: df[config.ID_COL]})
    for i, k in enumerate(keys):
        out[f"score_{k}"] = scores[:, i]
    for k in keys:
        out[f"pct_{k}"] = (out[f"score_{k}"].rank(pct=True) * 100).round(3)
    pct_cols = [f"pct_{k}" for k in keys]
    out["top_label"] = out[pct_cols].idxmax(axis=1).str[len("pct_"):]
    out = (out.assign(_max_pct=out[pct_cols].max(axis=1))
              .sort_values("_max_pct", ascending=False)
              .drop(columns="_max_pct")
              .reset_index(drop=True))

    out_dir = Path(output_dir) if output_dir else variant.artifact_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    all_path = out_dir / "candidate_scores.csv"
    out.to_csv(all_path, index=False)
    print(f"[INFO] 전체 스코어 저장({len(out)}명): {all_path}")

    threshold = 100 - top_pct
    flags = pd.DataFrame({f"in_top_{k}": out[f"pct_{k}"] > threshold for k in keys})
    selected = out.join(flags)[flags.any(axis=1)].copy()
    selected["selected_labels"] = flags[flags.any(axis=1)].apply(
        lambda r: ";".join(k for k in keys if r[f"in_top_{k}"]), axis=1)
    selected["n_selected"] = flags[flags.any(axis=1)].sum(axis=1).astype(int)
    selected["max_pct"] = selected[pct_cols].max(axis=1)
    selected = selected.sort_values("max_pct", ascending=False).drop(columns="max_pct")
    union_path = out_dir / f"candidate_scores_top{top_pct:g}pct.csv"
    selected.to_csv(union_path, index=False)
    print(f"[INFO] 라벨별 상위 {top_pct:g}% 합집합 {len(selected)}명 저장: {union_path}")

    for k in keys:
        top_k = selected[selected[f"in_top_{k}"]].sort_values(f"score_{k}", ascending=False)
        path = out_dir / f"top{top_pct:g}pct_{k}.csv"
        top_k.to_csv(path, index=False)
        print(f"  - {k}: {len(top_k)}명 -> {path.name}")
    print("[INFO] 선택된 라벨 수 분포: "
          + ", ".join(f"{n}개={c}명" for n, c in selected["n_selected"].value_counts().sort_index().items()))
    return out


def main():
    parser = argparse.ArgumentParser(description="멀티라벨 lookalike candidate 스코어링 + 라벨별 상위 후보 추출")
    parser.add_argument("--variant", choices=list(config.MULTILABEL_VARIANTS), required=True)
    parser.add_argument("--top-pct", type=float, default=10.0, help="라벨별 상위 N%%")
    parser.add_argument("--candidate-ids-csv", help="candidate device_ifa 목록 CSV (생략 시 variant 기본값)")
    parser.add_argument("--output-dir", help="결과 저장 디렉터리 (생략 시 variant.artifact_dir)")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    score(config.MULTILABEL_VARIANTS[args.variant], device=args.device, top_pct=args.top_pct,
          candidate_ids_csv=args.candidate_ids_csv, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
