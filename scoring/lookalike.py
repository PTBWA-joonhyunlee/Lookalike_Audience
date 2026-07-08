# scoring/lookalike.py
#
# 과거 캠페인에서 관심을 보인 "시드(seed)" 유저 집합의 임베딩 centroid를 만들고, 아직 반응
# 안 한 신규 유저(scoring target)의 임베딩이 그 centroid와 코사인 유사도로 얼마나 가까운지
# 스코어링한다. evaluation/distance.py(전체 N×N 거리 행렬)와 달리, 신규 유저 규모가 커도
# "centroid 1개 대비 거리"만 계산하므로 O(N)으로 끝난다.
#
# 입력: inference/user_profile.py, inference/media_sequence.py가 뽑은 임베딩 CSV
#   (req_user_id + emb_00..emb_63) 각각 pool(시드 후보 모수)용/target(신규 유저)용 2개씩,
#   총 4개 CSV. 두 임베딩은 req_user_id로 inner join해서 128차원 fused 벡터로 합친다(concat).
#
# CLI 실행:
#   .venv\Scripts\python.exe -m scoring.lookalike \
#     --pool-profile-emb data/embeddings/user_profile_apr_may.csv \
#     --pool-media-emb data/embeddings/media_sequence_apr_may.csv \
#     --seed-ids data/addi_seed_interested_users_apr_may.csv \
#     --target-profile-emb data/embeddings/user_profile_jun_new.csv \
#     --target-media-emb data/embeddings/media_sequence_jun_new.csv \
#     --output data/embeddings/lookalike_scored_jun.csv

import argparse

import numpy as np
import pandas as pd

ID_COL = "req_user_id"


def load_fused_embeddings(profile_path: str, media_path: str, id_col: str = ID_COL) -> pd.DataFrame:
    """user_profile/media_sequence 임베딩 CSV 2개를 req_user_id로 inner join해서 하나의
    DataFrame(id_col + emb_00..emb_127)으로 합친다. 두 임베딩이 다 있는 유저만 남는다 —
    한쪽만 있으면(예: 프로필은 있는데 방문 이벤트가 top500 필터에 하나도 안 걸린 경우)
    fused 벡터를 만들 수 없으므로 제외한다."""
    profile = pd.read_csv(profile_path)
    media = pd.read_csv(media_path)
    merged = profile.merge(media, on=id_col, suffixes=("_profile", "_media"))
    return merged


def l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1e-12
    return mat / norms


def compute_centroid(pool_df: pd.DataFrame, seed_ids: set, id_col: str = ID_COL) -> np.ndarray:
    """pool_df(fused 임베딩) 중 seed_ids에 속하는 행만 뽑아 L2-정규화 후 평균낸 centroid(단위
    벡터는 아님, 방향 평균)를 반환한다. 정규화 후 평균내는 이유: 벡터 크기(norm)가 큰 유저가
    평균을 과도하게 끌어당기지 않도록 방향만 동일 가중치로 반영하기 위함."""
    emb_cols = [c for c in pool_df.columns if c != id_col]
    mask = pool_df[id_col].astype(str).isin(seed_ids)
    coverage = mask.sum() / max(len(seed_ids), 1)
    print(f"[INFO] 시드 {len(seed_ids):,}명 중 pool에 임베딩 존재: {mask.sum():,}명 ({coverage:.1%})")
    if mask.sum() == 0:
        raise ValueError("시드 유저가 pool 임베딩과 하나도 겹치지 않습니다 — 샘플링/기간을 확인하세요.")

    seed_vecs = l2_normalize(pool_df.loc[mask, emb_cols].to_numpy(dtype=np.float64))
    centroid = seed_vecs.mean(axis=0)
    return centroid


def score_targets(target_df: pd.DataFrame, centroid: np.ndarray, id_col: str = ID_COL) -> pd.DataFrame:
    emb_cols = [c for c in target_df.columns if c != id_col]
    vecs = l2_normalize(target_df[emb_cols].to_numpy(dtype=np.float64))
    centroid_unit = centroid / max(np.linalg.norm(centroid), 1e-12)
    scores = vecs @ centroid_unit

    out = pd.DataFrame({id_col: target_df[id_col].astype(str), "lookalike_score": scores})
    return out.sort_values("lookalike_score", ascending=False).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(
        description="시드(과거 관심 유저) 임베딩 centroid 대비 신규 유저의 코사인 유사도를 스코어링한다."
    )
    parser.add_argument("--pool-profile-emb", required=True, help="시드 후보 모수의 user_profile 임베딩 CSV")
    parser.add_argument("--pool-media-emb", required=True, help="시드 후보 모수의 media_sequence 임베딩 CSV")
    parser.add_argument("--seed-ids", required=True, help="req_user_id 컬럼을 포함한 시드(관심 유저) CSV")
    parser.add_argument("--target-profile-emb", required=True, help="스코어링 대상(신규 유저)의 user_profile 임베딩 CSV")
    parser.add_argument("--target-media-emb", required=True, help="스코어링 대상(신규 유저)의 media_sequence 임베딩 CSV")
    parser.add_argument("--output", required=True, help="결과(req_user_id, lookalike_score) 저장 경로")
    parser.add_argument("--id-col", default=ID_COL)
    args = parser.parse_args()

    pool_df = load_fused_embeddings(args.pool_profile_emb, args.pool_media_emb, args.id_col)
    print(f"[INFO] pool fused 임베딩: {len(pool_df):,}명, 차원 {pool_df.shape[1] - 1}")

    seed_ids = set(pd.read_csv(args.seed_ids)[args.id_col].astype(str))
    centroid = compute_centroid(pool_df, seed_ids, args.id_col)

    target_df = load_fused_embeddings(args.target_profile_emb, args.target_media_emb, args.id_col)
    print(f"[INFO] target fused 임베딩: {len(target_df):,}명, 차원 {target_df.shape[1] - 1}")

    scored = score_targets(target_df, centroid, args.id_col)
    scored.to_csv(args.output, index=False)

    print(f"[INFO] 스코어링 완료: {args.output} ({len(scored):,}명)")
    print(scored["lookalike_score"].describe())


if __name__ == "__main__":
    main()
