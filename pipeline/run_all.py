# pipeline/run_all.py
#
# 학습(train)→추론(inference)→스코어링(scoring)을 하나의 커맨드로 순서대로 실행한다
# (config에서 backtest.enabled=true면 백테스트까지). 각 단계를 subprocess로 부르지 않고
# train/inference/scoring/evaluation 모듈의 재사용 가능한 함수를 직접 호출한다 — 그래서
# 이 모듈들의 개별 CLI(--config 포함)는 그대로 유지되고, 부분 재실행/디버깅엔 여전히
# 그쪽을 쓰면 된다(README.md §2 참고).
#
# 전제: querys/audience_embedding/01~05.sql을 Athena 콘솔에서 실행하고 결과 CSV를 config에
# 지정한 경로(기본 data/raw/)에 미리 올려둔 상태여야 한다 — 이 저장소는 Athena 접근 권한이
# 없다(README.md §1 참고). 06(postback, 백테스트 라벨)은 backtest.enabled=true일 때만 필요.
#
# CLI:
#   cp config/pipeline.example.json config/pipeline.json  # 값 채우기
#   .venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json
#   .venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json --skip-train
#     (모델이 이미 학습돼 있고 새 기간 신규 유저만 추론→스코어링하고 싶을 때)

import argparse
import os

import pandas as pd

import evaluation.backtest as backtest
import inference.media_sequence as infer_media
import inference.user_profile as infer_profile
import scoring.infer_supervised_lookalike as score_infer
import scoring.train_supervised_lookalike as score_train
import train.media_sequence as train_media
import train.user_profile as train_profile
from pipeline.config import load_pipeline_config
from scoring.fused_embeddings import ID_COL, load_fused_embeddings
from scoring.fusion_classifier import save_artifacts


def _save_csv(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df.to_csv(path, index=False)


def _infer_and_save(module, input_path: str, model_dir: str, output_path: str) -> None:
    df = pd.read_csv(input_path)
    emb_df = module.encode(df, artifact_dir=model_dir)
    _save_csv(emb_df, output_path)
    print(f"[INFO] 임베딩 저장: {output_path} ({len(emb_df):,}명)")


def run(cfg: dict, skip_train: bool = False) -> None:
    device = cfg.get("device", "auto")
    raw = cfg["raw"]
    models = cfg["models"]
    embeddings = cfg["embeddings"]
    train_cfg = cfg.get("train", {})

    if skip_train:
        print("=== [1/4] 학습: --skip-train, 건너뜀 (기존 모델 재사용) ===")
    else:
        print("=== [1/4] 학습: user_profile / media_sequence ===")
        train_profile.train(
            num_epochs=train_cfg.get("user_profile_num_epochs", 30),
            input_path=raw["user_profile"],
            artifact_dir=models["user_profile_dir"],
            device=device,
        )
        train_media.train(
            num_epochs=train_cfg.get("media_sequence_num_epochs", 30),
            input_path=raw["top500_media_visit"],
            artifact_dir=models["media_sequence_dir"],
            device=device,
        )

    print("=== [2/4] 추론: pool(4~5월)/target(신규 유저) 임베딩 추출 ===")
    _infer_and_save(infer_profile, raw["user_profile"], models["user_profile_dir"], embeddings["user_profile_pool"])
    _infer_and_save(infer_media, raw["top500_media_visit"], models["media_sequence_dir"], embeddings["media_sequence_pool"])
    _infer_and_save(infer_profile, raw["new_user_profile"], models["user_profile_dir"], embeddings["user_profile_target"])
    _infer_and_save(infer_media, raw["new_top500_media_visit"], models["media_sequence_dir"], embeddings["media_sequence_target"])

    print("=== [3/4] 스코어링: 지도학습 분류기 학습 + 신규 유저 스코어링 ===")
    pool_df = load_fused_embeddings(embeddings["user_profile_pool"], embeddings["media_sequence_pool"])
    seed_ids = set(pd.read_csv(raw["seed_ids"])[ID_COL].astype(str))
    classifier = score_train.train_classifier(
        pool_df,
        seed_ids,
        num_epochs=train_cfg.get("classifier_num_epochs", 20),
    )
    save_artifacts(classifier, models["fusion_classifier_dir"])

    target_df = load_fused_embeddings(embeddings["user_profile_target"], embeddings["media_sequence_target"])
    scored = score_infer.score(classifier, target_df)
    scoring_output = cfg["scoring_output"]
    _save_csv(scored, scoring_output)
    print(f"[INFO] 스코어링 결과 저장: {scoring_output} ({len(scored):,}명)")

    bt_cfg = cfg.get("backtest", {})
    if not bt_cfg.get("enabled", False):
        print("=== [4/4] 백테스트: backtest.enabled=false, 건너뜀 (실제 postback 쌓이면 활성화) ===")
        return

    print("=== [4/4] 백테스트 ===")
    labels_df = pd.read_csv(bt_cfg["labels"])
    id_map_path = bt_cfg.get("id_map") or raw.get("new_user_profile")
    id_map_df = pd.read_csv(id_map_path) if id_map_path else None
    result = backtest.run_backtest(
        scored=scored,
        labels=labels_df,
        scored_id_col=ID_COL,
        score_col="lookalike_score",
        label_id_col=bt_cfg["label_id_col"],
        label_col=bt_cfg["label_col"],
        label_threshold=bt_cfg.get("label_threshold", 1.0),
        id_map=id_map_df,
        map_from_col=bt_cfg.get("map_from_col"),
        map_to_col=bt_cfg.get("map_to_col"),
        n_buckets=bt_cfg.get("n_buckets", 10),
    )
    bt_output = bt_cfg["output"]
    _save_csv(result, bt_output)
    print(f"[INFO] 백테스트 결과 저장: {bt_output}")


def main():
    parser = argparse.ArgumentParser(
        description="학습→추론→스코어링(→백테스트)을 config 하나로 한번에 실행한다 (README.md §2 참고)."
    )
    parser.add_argument("--config", required=True, help="config/pipeline.example.json 참고")
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="모델이 이미 학습돼 있을 때 학습 단계를 건너뛴다 (새 기간 신규 유저 추론→스코어링만 반복할 때).",
    )
    args = parser.parse_args()

    cfg = load_pipeline_config(args.config)
    missing = [k for k in ("raw", "models", "embeddings", "scoring_output") if k not in cfg]
    if missing:
        parser.error(f"config에 다음 키가 없습니다: {missing}")

    run(cfg, skip_train=args.skip_train)


if __name__ == "__main__":
    main()
