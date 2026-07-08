# evaluation/distance.py
#
# inference/*.py가 뽑은 임베딩 CSV(req_user_id + emb_00..emb_NN)를 입력받아, 임베딩끼리
# 서로 얼마나 가까운지(코사인 거리)를 전체 N×N 행렬로 계산한다. "유사 오디언스 탐색"이
# 이 프로젝트의 목표라, 임베딩이 실제로 유사한 유저를 가깝게 배치하는지 눈으로 확인/디버깅할
# 때 쓴다.
#
# CLI 실행: .venv\Scripts\python.exe -m evaluation.distance --input <임베딩 csv> [--output <csv>]

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

# N명이면 행렬이 N^2이라, 이 이상이면 메모리/파일 크기를 미리 경고만 해준다(계산 자체는 막지 않음).
LARGE_N_WARNING_THRESHOLD = 5000


def compute_distance_matrix(df: pd.DataFrame, id_col: str = "req_user_id") -> pd.DataFrame:
    """임베딩 DataFrame(id_col + emb_* 컬럼) -> req_user_id x req_user_id 코사인 거리 행렬.
    거리 = 1 - cosine_similarity, 범위는 [0, 2] (완전히 같은 방향=0, 완전히 반대 방향=2)."""
    ids = df[id_col].astype(str).tolist()
    emb_cols = [c for c in df.columns if c != id_col]
    vectors = df[emb_cols].to_numpy(dtype=np.float64)

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-12  # 임베딩이 전부 0벡터인 경우(빈 시퀀스 등) 0으로 나누는 것 방지
    normalized = vectors / norms

    cosine_sim = normalized @ normalized.T
    distance = 1.0 - cosine_sim
    np.fill_diagonal(distance, 0.0)  # 자기 자신과의 거리는 부동소수점 오차 없이 정확히 0으로

    return pd.DataFrame(distance, index=ids, columns=ids)


def main():
    parser = argparse.ArgumentParser(
        description="임베딩 CSV(req_user_id + emb_00..)를 읽어 유저 간 코사인 거리 행렬을 계산한다."
    )
    parser.add_argument("--input", required=True, help="임베딩 CSV 경로 (inference/*.py 산출물, id_col + emb_00.. 컬럼)")
    parser.add_argument("--output", help="결과 저장 경로 (생략 시 <입력파일명>_distance.csv를 같은 폴더에 저장)")
    parser.add_argument("--id-col", default="req_user_id", help="유저 식별자 컬럼명 (기본: req_user_id)")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    n = len(df)
    if n > LARGE_N_WARNING_THRESHOLD:
        print(f"[WARN] 유저 {n:,}명 → {n:,}x{n:,} 거리 행렬 (약 {n * n * 8 / 1e9:.1f}GB, 메모리/디스크 확인)")

    dist_df = compute_distance_matrix(df, id_col=args.id_col)

    output = args.output
    if not output:
        input_path = Path(args.input)
        output = str(input_path.with_name(f"{input_path.stem}_distance.csv"))
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    dist_df.to_csv(output, index_label=args.id_col)
    print(f"[INFO] 거리 행렬 저장: {output} ({n:,} x {n:,})")


if __name__ == "__main__":
    main()
