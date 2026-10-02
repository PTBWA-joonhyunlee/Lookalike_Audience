# lookalike/embedding/segment_features/build_features_incremental.py
#
# build_features_je.py를 일반화한 버전 — data/seed/ 밑의 임의의 *_segment.csv 하나를
# 기존 age_vocab/BERT lookup(재학습 없음)으로만 인코딩해 npz로 만든다. je seed뿐 아니라
# candidates_202606_0818(2026-08-19, 후보 규모 확장) 같은 "이미 학습된 모델/vocab을
# 그대로 쓰되 새 population만 추가 인코딩"해야 하는 모든 경우에 재사용한다.
#
# 실행(lookalike/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m embedding.segment_features.build_features_incremental ^
#     --csv candidate_segment.csv --tag candidate_0818

import argparse

import numpy as np
import pandas as pd

from . import config
from .bert_lookup import SegmentEmbeddingLookup
from .build_features import build
from ..common.vocab import CategoryVocab


def build_npz(csv_path, tag: str, skip_ids: set = None):
    """csv_path를 기존 vocab/lookup으로 인코딩해 segment_features_<tag>.npz로 저장한다.
    skip_ids를 주면 그 device_ifa는 인코딩 전에 걸러낸다(예: 이미 임베딩된 candidate를
    다시 인코딩하는 비용을 피할 때 — pipeline/run_new_seed_pipeline.py 참고). 걸러낸 뒤
    남는 행이 없으면 None을 반환한다."""
    df = pd.read_csv(csv_path, dtype=str)
    if skip_ids:
        df = df[~df[config.ID_COL].isin(skip_ids)].reset_index(drop=True)
    if df.empty:
        return None

    lookup = SegmentEmbeddingLookup.load(config.BERT_LOOKUP_PATH)
    age_vocab = CategoryVocab.load(config.AGE_VOCAB_PATH)
    features, _ = build(df, lookup, age_vocab=age_vocab)

    out_npz = config.ARTIFACT_DIR / f"segment_features_{tag}.npz"
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_npz, **features)
    print(f"{len(df)} devices -> {out_npz}")
    return out_npz


def main():
    parser = argparse.ArgumentParser(description="기존 vocab/lookup으로 population 하나만 인코딩")
    parser.add_argument("--csv", required=True, help="data/seed/ 밑 입력 CSV 파일명(예: candidate_segment.csv)")
    parser.add_argument("--tag", required=True, help="출력 npz 파일명 접두어(예: candidate_0818 -> segment_features_candidate_0818.npz)")
    args = parser.parse_args()

    build_npz(config.DATA_DIR / args.csv, args.tag)


if __name__ == "__main__":
    main()
