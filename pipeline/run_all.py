# pipeline/run_all.py
#
# 학습(train)→추론(inference)→[층화 pool 병합]→스코어링(scoring)을 하나의 커맨드로 순서대로
# 실행한다(config에서 backtest.enabled=true면 백테스트까지). 각 단계를 subprocess로 부르지
# 않고 train/inference/scoring/evaluation 모듈의 재사용 가능한 함수를 직접 호출한다 — 그래서
# 이 모듈들의 개별 CLI(--config 포함)는 그대로 유지되고, 부분 재실행/디버깅엔 여전히
# 그쪽을 쓰면 된다(README.md 참고).
#
# 전제: querys/pipeline/01~08.sql을 Athena 콘솔에서 실행하고 결과 CSV를 config에 지정한
# 경로(기본 data/raw/)에 미리 올려둔 상태여야 한다 — 이 저장소는 Athena 접근 권한이 없다
# (README.md 참고). 06(백테스트 라벨)은 backtest.enabled=true일 때만 필요.
#
# stratify: 시드(양성) 유저가 pool의 5% 샘플에 충분히 안 남을 만큼 희소할 때 쓴다(양성만
# 전수 조회한 04/05 raw CSV를 넣어주면, 이 스크립트가 임베딩 추론 후 기존 pool 임베딩에
# scoring.build_stratified_pool로 병합한다). config에 stratify 블록이 없으면 pool을 그대로
# 쓴다(하위 호환).
#
# CLI:
#   cp config/pipeline.example.json config/pipeline.json  # 값 채우기
#   .venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json
#   .venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json --skip-train
#     (모델이 이미 학습돼 있고 새 기간 스코어링 대상만 추론→스코어링하고 싶을 때)

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
from scoring.build_stratified_pool import build_stratified_pool
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
    stratify_cfg = cfg.get("stratify")

    if skip_train:
        print("=== [1/5] 학습: --skip-train, 건너뜀 (기존 모델 재사용) ===")
    else:
        print("=== [1/5] 학습: user_profile / media_sequence ===")
        train_profile.train(
            num_epochs=train_cfg.get("user_profile_num_epochs", 30),
            input_path=raw["pool_profile"],
            artifact_dir=models["user_profile_dir"],
            device=device,
        )
        train_media.train(
            num_epochs=train_cfg.get("media_sequence_num_epochs", 30),
            input_path=raw["pool_media"],
            artifact_dir=models["media_sequence_dir"],
            device=device,
        )

    print("=== [2/5] 추론: pool / 스코어링 대상 임베딩 추출 ===")
    _infer_and_save(infer_profile, raw["pool_profile"], models["user_profile_dir"], embeddings["pool_profile"])
    _infer_and_save(infer_media, raw["pool_media"], models["media_sequence_dir"], embeddings["pool_media"])
    _infer_and_save(infer_profile, raw["target_profile"], models["user_profile_dir"], embeddings["target_profile"])
    _infer_and_save(infer_media, raw["target_media"], models["media_sequence_dir"], embeddings["target_media"])

    pool_profile_emb = embeddings["pool_profile"]
    pool_media_emb = embeddings["pool_media"]

    if stratify_cfg:
        print("=== [3/5] 시드 임베딩 추론 + 층화 pool 병합 (음성 5% 샘플 + 양성 전수) ===")
        _infer_and_save(
            infer_profile, stratify_cfg["seed_profile_raw"], models["user_profile_dir"], stratify_cfg["seed_profile_emb"]
        )
        _infer_and_save(
            infer_media, stratify_cfg["seed_media_raw"], models["media_sequence_dir"], stratify_cfg["seed_media_emb"]
        )

        merged_profile = build_stratified_pool(pd.read_csv(pool_profile_emb), pd.read_csv(stratify_cfg["seed_profile_emb"]))
        _save_csv(merged_profile, stratify_cfg["pool_profile_stratified"])
        merged_media = build_stratified_pool(pd.read_csv(pool_media_emb), pd.read_csv(stratify_cfg["seed_media_emb"]))
        _save_csv(merged_media, stratify_cfg["pool_media_stratified"])

        pool_profile_emb = stratify_cfg["pool_profile_stratified"]
        pool_media_emb = stratify_cfg["pool_media_stratified"]
    else:
        print("=== [3/5] 층화 pool 병합: config에 stratify 없음, 건너뜀 (pool 그대로 사용) ===")

    print("=== [4/5] 스코어링: 지도학습 분류기 학습 + 스코어링 대상 스코어 생성 ===")
    pool_df = load_fused_embeddings(pool_profile_emb, pool_media_emb)
    seed_ids = set(pd.read_csv(raw["seed_ids"])[ID_COL].astype(str))
    classifier = score_train.train_classifier(
        pool_df,
        seed_ids,
        num_epochs=train_cfg.get("classifier_num_epochs", 20),
        pos_frac=train_cfg.get("pos_frac", 0.1),
        topk_pct=train_cfg.get("topk_pct", 0.1),
    )
    save_artifacts(classifier, models["fusion_classifier_dir"])

    target_df = load_fused_embeddings(embeddings["target_profile"], embeddings["target_media"])
    scored = score_infer.score(classifier, target_df)
    scoring_output = cfg["scoring_output"]
    _save_csv(scored, scoring_output)
    print(f"[INFO] 스코어링 결과 저장: {scoring_output} ({len(scored):,}명)")

    bt_cfg = cfg.get("backtest", {})
    if not bt_cfg.get("enabled", False):
        print("=== [5/5] 백테스트: backtest.enabled=false, 건너뜀 (실제 postback 쌓이면 활성화) ===")
        return

    print("=== [5/5] 백테스트 ===")
    labels_df = pd.read_csv(bt_cfg["labels"])
    id_map_path = bt_cfg.get("id_map") or raw.get("target_profile")
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

    cumulative_output = bt_cfg.get("cumulative_output")
    if cumulative_output:
        cumulative = backtest.cumulative_topk_summary(result, score_col="lookalike_score")
        os.makedirs(os.path.dirname(cumulative_output) or ".", exist_ok=True)
        cumulative.to_csv(cumulative_output)
        print(f"[INFO] 누적 top-K% 결과 저장: {cumulative_output}")


def main():
    parser = argparse.ArgumentParser(
        description="학습→추론→[층화 pool 병합]→스코어링(→백테스트)을 config 하나로 한번에 실행한다 (README.md 참고)."
    )
    parser.add_argument("--config", required=True, help="config/pipeline.example.json 참고")
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="모델이 이미 학습돼 있을 때 학습 단계를 건너뛴다 (새 기간 스코어링 대상만 추론→스코어링만 반복할 때).",
    )
    args = parser.parse_args()

    cfg = load_pipeline_config(args.config)
    missing = [k for k in ("raw", "models", "embeddings", "scoring_output") if k not in cfg]
    if missing:
        parser.error(f"config에 다음 키가 없습니다: {missing}")

    run(cfg, skip_train=args.skip_train)


if __name__ == "__main__":
    main()
