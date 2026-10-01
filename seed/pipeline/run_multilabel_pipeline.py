# seed/pipeline/run_multilabel_pipeline.py
#
# 멀티라벨 variant(scoring.config.MULTILABEL_VARIANTS)의 Python 단계를 한 번에 실행한다:
# 라벨별 seed segment 인코딩 -> candidate 인코딩 -> 멀티헤드 분류기 학습 -> candidate
# 스코어링 + 라벨별 상위 N% 추출. 인코딩은 run_new_seed_pipeline.encode_and_append를 그대로
# 쓴다(기존 학습된 BERT lookup/Autoencoder forward만, 이미 인코딩된 device_ifa는 스킵).
#
# 준비물: variant의 각 Label.seed_ids_csv(data/seed/seed_segment_<key>.csv)와
# candidate_ids_csv — Athena에서 segment/02_seed_segment_<key>.sql,
# segment/04_candidate_segment_*.sql 결과로 받는다(CLAUDE.md "데이터를 얻는 방법").
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m pipeline.run_multilabel_pipeline --variant military --top-pct 10

import argparse

from pipeline.run_new_seed_pipeline import encode_and_append
from scoring import config as scoring_config
from scoring.infer_multilabel import score
from scoring.train_multilabel import train


def run_pipeline(variant_name: str, top_pct: float = 10.0, epochs: int = scoring_config.NUM_EPOCHS,
                 batch_size: int = scoring_config.BATCH_SIZE, lr: float = scoring_config.LEARNING_RATE,
                 val_split: float = scoring_config.VAL_SPLIT, hidden_dim: int = scoring_config.MULTILABEL_HIDDEN_DIM,
                 device: str = "auto", skip_encode: bool = False) -> None:
    variant = scoring_config.MULTILABEL_VARIANTS[variant_name]

    missing = [p for p in [lb.seed_ids_csv for lb in variant.labels] + [variant.candidate_ids_csv] if not p.exists()]
    if missing:
        raise FileNotFoundError("입력 CSV가 없습니다:\n" + "\n".join(f"  - {p}" for p in missing))

    if skip_encode:
        print("[STEP 1/3] 인코딩 스킵(--skip-encode)")
    else:
        for lb in variant.labels:
            print(f"[STEP 1/3] seed segment 인코딩({lb.key}): {lb.seed_ids_csv}")
            encode_and_append(lb.seed_ids_csv, tag=lb.key)
        print(f"[STEP 1/3] candidate segment 인코딩: {variant.candidate_ids_csv}")
        encode_and_append(variant.candidate_ids_csv, tag=f"candidate_{variant.name}")

    print(f"[STEP 2/3] 멀티헤드 분류기 학습: variant={variant.name}")
    train(variant, num_epochs=epochs, batch_size=batch_size, lr=lr, val_split=val_split,
          hidden_dim=hidden_dim, device=device)

    print(f"[STEP 3/3] candidate 스코어링 + 라벨별 상위 {top_pct:g}% 추출")
    score(variant, device=device, top_pct=top_pct)

    print(f"[DONE] 결과: {variant.artifact_dir}")


def main():
    parser = argparse.ArgumentParser(description="멀티라벨 lookalike 파이프라인(인코딩 -> 학습 -> 스코어링 -> 라벨별 top N) 일괄 실행")
    parser.add_argument("--variant", choices=list(scoring_config.MULTILABEL_VARIANTS), required=True)
    parser.add_argument("--top-pct", type=float, default=10.0)
    parser.add_argument("--epochs", type=int, default=scoring_config.NUM_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=scoring_config.BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=scoring_config.LEARNING_RATE)
    parser.add_argument("--val-split", type=float, default=scoring_config.VAL_SPLIT)
    parser.add_argument("--hidden-dim", type=int, default=scoring_config.MULTILABEL_HIDDEN_DIM)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--skip-encode", action="store_true", help="seed/candidate가 이미 인코딩돼 있을 때")
    args = parser.parse_args()

    run_pipeline(args.variant, top_pct=args.top_pct, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
                 val_split=args.val_split, hidden_dim=args.hidden_dim, device=args.device, skip_encode=args.skip_encode)


if __name__ == "__main__":
    main()
