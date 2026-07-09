# scoring/build_stratified_pool.py
#
# 학습 pool(예: data/embeddings/user_profile_apr_may.csv)은 데이터량 때문에 유저 단위 5%
# 샘플링이 걸려 있다(README.md §1). 시드(양성) 정의를 postback tier에서 IP 매칭 전환으로
# 바꾸면서 양성 절대 건수가 너무 작아져(docs/_archive/202607091533.md), 5% 샘플 안에 남는
# 양성이 극소수가 되는 문제가 생겼다 — 음성은 5% 샘플을 유지하되 양성(시드)은 전수 포함시켜야
# 학습이 가능하다.
#
# 이 스크립트는 그 병합을 담당한다: (1) 기존 5% 샘플 pool 임베딩, (2) 시드(양성) 유저만
# 5% 샘플과 무관하게 별도로 전수 추론한 임베딩 — 이 둘을 id_col 기준으로 합치고 중복을
# 제거한다(우연히 5% 샘플에 이미 포함된 양성 유저가 있으면 전수 버전을 남긴다). user_profile/
# media_sequence 임베딩 각각에 대해 한 번씩 실행해야 한다(임베딩 종류 무관하게 동작 — id_col +
# 피처 컬럼 구조만 보고 병합).
#
# CLI:
#   .venv\Scripts\python.exe -m scoring.build_stratified_pool \
#     --sampled-emb data/embeddings/user_profile_apr_may.csv \
#     --full-emb data/embeddings/user_profile_conv_matched_apr_may.csv \
#     --output data/embeddings/user_profile_apr_may_stratified.csv
#
#   .venv\Scripts\python.exe -m scoring.build_stratified_pool \
#     --sampled-emb data/embeddings/media_sequence_apr_may.csv \
#     --full-emb data/embeddings/media_sequence_conv_matched_apr_may.csv \
#     --output data/embeddings/media_sequence_apr_may_stratified.csv

import argparse

import pandas as pd

from scoring.fused_embeddings import ID_COL


def build_stratified_pool(sampled: pd.DataFrame, full: pd.DataFrame, id_col: str = ID_COL) -> pd.DataFrame:
    sampled = sampled.copy()
    full = full.copy()
    sampled[id_col] = sampled[id_col].astype(str)
    full[id_col] = full[id_col].astype(str)

    overlap = sampled[id_col].isin(full[id_col]).sum()
    print(
        f"[INFO] 샘플 pool {len(sampled):,}명 + 전수 병합 대상 {len(full):,}명 "
        f"(겹침 {overlap:,}명, 전수 버전으로 대체됨)"
    )

    merged = pd.concat([sampled, full], ignore_index=True)
    merged = merged.drop_duplicates(subset=[id_col], keep="last")
    print(f"[INFO] 병합 결과: {len(merged):,}명")
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="5% 샘플 pool 임베딩에 전수 조회한 양성(시드) 유저 임베딩을 병합한다."
    )
    parser.add_argument("--sampled-emb", required=True, help="기존 5%% 샘플 pool 임베딩 CSV")
    parser.add_argument("--full-emb", required=True, help="샘플링 없이 전수 조회한 양성 유저 임베딩 CSV")
    parser.add_argument("--id-col", default=ID_COL)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    sampled = pd.read_csv(args.sampled_emb)
    full = pd.read_csv(args.full_emb)
    merged = build_stratified_pool(sampled, full, id_col=args.id_col)
    merged.to_csv(args.output, index=False)
    print(f"[INFO] 저장: {args.output}")


if __name__ == "__main__":
    main()
