# scoring/infer_supervised_lookalike.py
#
# train_supervised_lookalike.py로 학습해 저장한 분류기 아티팩트(model.pt, meta.json)를
# 재학습 없이 불러와, 새 target 유저의 fused 임베딩(user_profile+media_sequence concat)에
# lookalike_score를 매긴다.
#
# CLI:
#   .venv\Scripts\python.exe -m scoring.infer_supervised_lookalike \
#     --model-dir data/models/fusion_classifier_addi \
#     --target-profile-emb data/embeddings/user_profile_jun_new.csv \
#     --target-media-emb data/embeddings/media_sequence_jun_new.csv \
#     --output data/embeddings/supervised_lookalike_scored_jun.csv
#
# --config: 위 옵션들을 담은 JSON 설정 파일 (config/infer_supervised_lookalike.example.json
#   참고). 개별 CLI 옵션을 같이 주면 그 값이 config보다 우선한다.

import argparse

import numpy as np
import pandas as pd
import torch

from scoring.fusion_classifier import FusionClassifier, load_artifacts
from scoring.fused_embeddings import ID_COL, load_fused_embeddings
from scoring.infer_config import load_infer_config


def score(model: FusionClassifier, target_df: pd.DataFrame, id_col: str = ID_COL) -> pd.DataFrame:
    emb_cols = [c for c in target_df.columns if c != id_col]
    X = torch.from_numpy(target_df[emb_cols].to_numpy(dtype=np.float32))
    model.eval()
    with torch.no_grad():
        probs = torch.sigmoid(model(X)).numpy()
    out = pd.DataFrame({id_col: target_df[id_col].astype(str), "lookalike_score": probs})
    return out.sort_values("lookalike_score", ascending=False).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="학습된 fusion 분류기로 재학습 없이 신규 유저를 스코어링한다.")
    parser.add_argument("--model-dir", help="train_supervised_lookalike.py가 저장한 분류기 아티팩트 경로")
    parser.add_argument("--target-profile-emb")
    parser.add_argument("--target-media-emb")
    parser.add_argument("--output")
    parser.add_argument("--id-col", default=None)
    parser.add_argument(
        "--config",
        help="model_dir/target_profile_emb/target_media_emb/output/id_col을 담은 JSON 설정 파일 "
        "(config/infer_supervised_lookalike.example.json 참고). 개별 CLI 옵션을 같이 주면 그 값이 "
        "config보다 우선한다.",
    )
    args = parser.parse_args()

    cfg = load_infer_config(args.config) if args.config else {}
    model_dir = args.model_dir or cfg.get("model_dir")
    target_profile_emb = args.target_profile_emb or cfg.get("target_profile_emb")
    target_media_emb = args.target_media_emb or cfg.get("target_media_emb")
    output = args.output or cfg.get("output")
    id_col = args.id_col or cfg.get("id_col", ID_COL)

    missing = [
        name
        for name, val in [
            ("--model-dir", model_dir),
            ("--target-profile-emb", target_profile_emb),
            ("--target-media-emb", target_media_emb),
            ("--output", output),
        ]
        if not val
    ]
    if missing:
        parser.error(f"{', '.join(missing)}을(를) 주거나 --config에 해당 키를 지정해야 한다.")

    model = load_artifacts(model_dir)

    target_df = load_fused_embeddings(target_profile_emb, target_media_emb, id_col)
    print(f"[INFO] target fused 임베딩: {len(target_df):,}명, 차원 {target_df.shape[1] - 1}")

    scored = score(model, target_df, id_col)
    scored.to_csv(output, index=False)
    print(f"[INFO] 스코어링 완료: {output} ({len(scored):,}명)")
    print(scored["lookalike_score"].describe())


if __name__ == "__main__":
    main()
