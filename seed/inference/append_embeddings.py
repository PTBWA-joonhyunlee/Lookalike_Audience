# seed/inference/append_embeddings.py
#
# merge_embeddings_je.py를 일반화한 버전 — inference.segment_features가 만든 임베딩
# CSV(--src)를 기존 segment_embeddings.csv(--dst, 기본값)에 이어붙인다. je 때와 달리
# candidate 규모 확장(candidates_202606_0818)처럼 --src에 **이미 dst에 들어있는 device_ifa
# 가 섞여 있을 수 있는 경우**(예: 06월 후보 664,684명은 이미 인코딩돼 있고, 07~08월18일로
# 추가된 인원만 새로 인코딩한 게 아니라 06~08월18일 전체를 다시 인코딩한 경우)를 위해,
# dst에 이미 있는 device_ifa는 건너뛰고 새 device_ifa만 append한다(파일 중복 비대화 방지).
# dst의 device_ifa 컬럼만 먼저 스트리밍으로 읽어 메모리에 올리고(2.2GB 전체를 올리지
# 않음), --src를 청크 단위로 순회하며 필터링한다.
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m inference.append_embeddings ^
#     --src ..\data\models\segment_features\segment_embeddings_candidate_0818.csv

import argparse
from pathlib import Path

import pandas as pd

from embedding.segment_features import config

DEFAULT_DST = config.ARTIFACT_DIR / "segment_embeddings.csv"


def append_dedup(src, dst=DEFAULT_DST, chunksize: int = 200_000) -> int:
    """src(임베딩 CSV)에서 dst에 아직 없는 device_ifa만 append한다. dst가 없으면(신규
    트랙 등) 헤더를 새로 쓰며 만든다 — 기존 스크립트는 dst가 항상 존재한다고 가정했지만
    pipeline/run_new_seed_pipeline.py처럼 범용으로 호출될 때는 그 가정이 항상 맞지 않는다."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        print(f"[INFO] {dst}의 기존 device_ifa 로드 중...")
        existing_ids = set(pd.read_csv(dst, usecols=[config.ID_COL], dtype=str)[config.ID_COL])
    else:
        existing_ids = set()
    print(f"[INFO] 기존 {len(existing_ids)}명")

    n_appended = 0
    write_header = not dst.exists()
    with open(dst, "a", encoding="utf-8", newline="") as out:
        for chunk in pd.read_csv(src, dtype={config.ID_COL: str}, chunksize=chunksize):
            new_rows = chunk[~chunk[config.ID_COL].isin(existing_ids)]
            if new_rows.empty:
                continue
            new_rows.to_csv(out, header=write_header, index=False)
            write_header = False
            n_appended += len(new_rows)

    print(f"[INFO] 신규 {n_appended}명을 {dst}에 append 완료(중복 {len(existing_ids)}명은 건너뜀)")
    return n_appended


def main():
    parser = argparse.ArgumentParser(description="임베딩 CSV를 기존 segment_embeddings.csv에 중복 없이 append")
    parser.add_argument("--src", required=True, help="append할 임베딩 CSV 경로")
    parser.add_argument("--dst", default=str(DEFAULT_DST), help="병합 대상 CSV 경로(기본: segment_embeddings.csv)")
    parser.add_argument("--chunksize", type=int, default=200_000)
    args = parser.parse_args()

    append_dedup(args.src, args.dst, args.chunksize)


if __name__ == "__main__":
    main()
