# seed/pipeline/run_new_seed_pipeline.py
#
# 신규 seed가 들어왔을 때 Python 쪽 파이프라인(임베딩 인코딩 -> 분류기 학습 -> candidate
# 스코어링 -> 상위 N% 추출)을 한 번에 실행한다. 이 repo에는 Athena 접근 권한이 없어
# seed/seed_ad_id/seed_segment/candidate/candidate_segment 테이블 생성(SQL) 단계는
# 자동화할 수 없다 — 사용자가 Athena 콘솔에서 해당 SQL을 실행하고 결과 CSV를
# data/seed/에 내려받은 뒤(CLAUDE.md "데이터를 얻는 방법" 참고) 이 스크립트를 실행한다.
#
# je seed(2026-08-19)에서 손으로 반복했던 아래 단계를 하나로 묶었다:
#   build_features_je.py(seed 인코딩) -> inference.segment_features(임베딩 추출) ->
#   append_embeddings.py(중복 없이 병합) -> [candidate도 동일하게 반복] ->
#   scoring/config.py에 Variant 수동 추가 -> train_lookalike.py -> infer_lookalike.py
# Variant는 scoring/config.py를 고치지 않고 이 스크립트가 즉석에서 만든다 — 신규 seed마다
# config.py에 SEED_<NAME>_IDS_CSV/Variant를 손으로 추가할 필요가 없다.
#
# 재학습은 하지 않는다 — segment_features 인코딩은 기존 학습된 BERT lookup/Autoencoder
# (embedding/segment_features/config.ARTIFACT_DIR의 model.pt)를 forward로만 쓴다. 학습이
# 일어나는 건 seed=1/pool=0 라벨의 LookalikeClassifier(scoring/train_lookalike.py)뿐이다.
#
# 준비물:
#   - data/seed/seed_segment_<name>.csv (신규 seed segment, segment/02_seed_segment_*.sql 결과)
#   - data/seed/candidate_segment.csv (candidate segment, 기본은 기존 걸 그대로 재사용)
#   - pool은 기본으로 scoring.config.POOL_IDS_CSV(피엘라벤 pool)를 재사용한다(je 때 판단과
#     동일 — pool은 특정 seed 브랜드에 종속되지 않는 일반 모집단이라 재사용 가능. 신규 seed가
#     pool과 겹치는 게 걱정되면 seed 제외 처리된 pool CSV를 --pool-ids-csv로 넘길 것).
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m pipeline.run_new_seed_pipeline --seed-name je --top-pct 10

import argparse
from pathlib import Path

import pandas as pd

from embedding.segment_features import build_features_incremental
from embedding.segment_features import config as feat_config
from inference import append_embeddings
from inference import segment_features as infer_segment_features
from scoring import config as scoring_config
from scoring.infer_lookalike import score
from scoring.train_lookalike import train


def encode_and_append(csv_path: Path, tag: str, dst: Path = None) -> int:
    """csv_path(seed/candidate segment CSV)에서 dst(기본 segment_embeddings.csv)에 아직 없는
    device_ifa만 골라 기존 학습된 BERT lookup + Autoencoder로 인코딩해 append한다(재학습 없음,
    forward만). 전원 이미 인코딩돼 있으면 인코딩 자체를 건너뛴다(candidate가 수백만 행이라
    재실행마다 다시 인코딩하면 비용이 크다). 반환값: 새로 추가된 인원 수."""
    dst = Path(dst) if dst else scoring_config.SEGMENT_EMBEDDINGS_CSV
    existing_ids = (
        set(pd.read_csv(dst, usecols=[feat_config.ID_COL], dtype=str)[feat_config.ID_COL])
        if dst.exists() else set()
    )

    npz_path = build_features_incremental.build_npz(csv_path, tag, skip_ids=existing_ids)
    if npz_path is None:
        print(f"[INFO] {csv_path.name}: 전원 이미 인코딩됨({len(existing_ids)}명 중), 스킵")
        return 0

    tmp_csv = feat_config.ARTIFACT_DIR / f"segment_embeddings_{tag}_new.csv"
    infer_segment_features.run(input_path=str(npz_path), output_path=str(tmp_csv))
    return append_embeddings.append_dedup(tmp_csv, dst)


def run_pipeline(
    seed_name: str,
    seed_segment_csv: str = None,
    candidate_segment_csv: str = None,
    pool_ids_csv: str = None,
    top_pct: float = 10.0,
    epochs: int = scoring_config.NUM_EPOCHS,
    batch_size: int = scoring_config.BATCH_SIZE,
    lr: float = scoring_config.LEARNING_RATE,
    val_split: float = scoring_config.VAL_SPLIT,
    device: str = "auto",
    skip_candidate_encode: bool = False,
) -> None:
    data_dir = scoring_config.PROJECT_ROOT / "data" / "seed"
    seed_segment_csv = Path(seed_segment_csv) if seed_segment_csv else data_dir / f"seed_segment_{seed_name}.csv"
    candidate_segment_csv = Path(candidate_segment_csv) if candidate_segment_csv else scoring_config.CANDIDATE_IDS_CSV
    pool_ids_csv = Path(pool_ids_csv) if pool_ids_csv else scoring_config.POOL_IDS_CSV

    print(f"[STEP 1/4] seed segment 인코딩: {seed_segment_csv}")
    encode_and_append(seed_segment_csv, tag=seed_name)

    if skip_candidate_encode:
        print("[STEP 2/4] candidate 인코딩 스킵(--skip-candidate-encode)")
    else:
        print(f"[STEP 2/4] candidate segment 인코딩: {candidate_segment_csv}")
        encode_and_append(candidate_segment_csv, tag=f"candidate_{seed_name}")

    variant = scoring_config.Variant(
        name=f"segment_{seed_name}",
        sources=[(scoring_config.SEGMENT_EMBEDDINGS_CSV, scoring_config.SEGMENT_EMBED_COLS)],
        artifact_dir=scoring_config.PROJECT_ROOT / "data" / "models" / f"lookalike_classifier_{seed_name}",
        seed_ids_csv=seed_segment_csv,
        pool_ids_csv=pool_ids_csv,
        candidate_ids_csv=candidate_segment_csv,
    )

    print(f"[STEP 3/4] 분류기 학습: variant={variant.name}")
    train(variant, num_epochs=epochs, batch_size=batch_size, lr=lr, val_split=val_split, device=device)

    print(f"[STEP 4/4] candidate 스코어링 + 상위 {top_pct}% 추출")
    score(variant, device=device, top_pct=top_pct)

    print(f"[DONE] 결과: {variant.artifact_dir}")


def main():
    parser = argparse.ArgumentParser(description="신규 seed 파이프라인(인코딩 -> 학습 -> 스코어링 -> top N) 일괄 실행")
    parser.add_argument("--seed-name", required=True, help='예: "je" -> data/seed/seed_segment_je.csv, variant "segment_je"')
    parser.add_argument("--seed-segment-csv", help="기본: data/seed/seed_segment_<name>.csv")
    parser.add_argument("--candidate-segment-csv", help="기본: scoring.config.CANDIDATE_IDS_CSV(candidate_segment.csv)")
    parser.add_argument("--pool-ids-csv", help="기본: scoring.config.POOL_IDS_CSV(pool_segment.csv, 기존 pool 재사용)")
    parser.add_argument("--top-pct", type=float, default=10.0)
    parser.add_argument("--epochs", type=int, default=scoring_config.NUM_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=scoring_config.BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=scoring_config.LEARNING_RATE)
    parser.add_argument("--val-split", type=float, default=scoring_config.VAL_SPLIT)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--skip-candidate-encode", action="store_true", help="candidate가 이미 인코딩돼 있을 때(재실행 시간 절약)")
    args = parser.parse_args()

    run_pipeline(
        seed_name=args.seed_name,
        seed_segment_csv=args.seed_segment_csv,
        candidate_segment_csv=args.candidate_segment_csv,
        pool_ids_csv=args.pool_ids_csv,
        top_pct=args.top_pct,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        val_split=args.val_split,
        device=args.device,
        skip_candidate_encode=args.skip_candidate_encode,
    )


if __name__ == "__main__":
    main()
