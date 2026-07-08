# evaluation/backtest.py
#
# scoring/*.py가 뽑은 스코어(예: lookalike_score)가 실제 결과(라벨)와 상관이 있는지 확인한다.
# 스코어 CSV와 라벨 CSV를 각각 다른 ID 체계로 갖고 있을 수 있어(예: 스코어는 req_user_id,
# 라벨은 device_ifa) 선택적으로 id-map CSV를 거쳐 조인한다. 라벨은 이진(0/1)이거나, 숫자
# 컬럼 + threshold로 이진화한다. 완전히 범용이라 어떤 스코어링 결과에도 재사용 가능 — "어떤
# log_type을 전환으로 볼지" 같은 도메인 지식은 라벨 CSV를 만드는 SQL 쪽 책임이다.
#
# CLI 실행:
#   .venv\Scripts\python.exe -m evaluation.backtest \
#     --scored data/embeddings/lookalike_scored_jun.csv --score-col lookalike_score --scored-id-col req_user_id \
#     --labels data/addi_postback_max_tier_jun.csv --label-col max_tier --label-id-col ifa --label-threshold 1 \
#     --id-map data/addi_new_users_user_profile_jun.csv --map-from-col req_user_id --map-to-col device_ifa \
#     --output data/embeddings/lookalike_scored_jun_backtest.csv

import argparse

import pandas as pd


def run_backtest(
    scored: pd.DataFrame,
    labels: pd.DataFrame,
    scored_id_col: str,
    score_col: str,
    label_id_col: str,
    label_col: str,
    label_threshold: float,
    id_map: pd.DataFrame = None,
    map_from_col: str = None,
    map_to_col: str = None,
    n_buckets: int = 10,
) -> pd.DataFrame:
    df = scored[[scored_id_col, score_col]].copy()
    df[scored_id_col] = df[scored_id_col].astype(str)

    join_id_col = scored_id_col
    if id_map is not None:
        mapping = id_map[[map_from_col, map_to_col]].drop_duplicates()
        mapping[map_from_col] = mapping[map_from_col].astype(str)
        mapping[map_to_col] = mapping[map_to_col].astype(str)
        df = df.merge(mapping, left_on=scored_id_col, right_on=map_from_col, how="left")
        matched = df[map_to_col].notna().sum()
        print(f"[INFO] id-map 매핑: {matched:,} / {len(df):,}")
        join_id_col = map_to_col

    labels = labels[[label_id_col, label_col]].copy()
    labels[label_id_col] = labels[label_id_col].astype(str)
    df = df.merge(labels, left_on=join_id_col, right_on=label_id_col, how="left")

    df[label_col] = df[label_col].fillna(0)
    df["label"] = df[label_col] >= label_threshold

    overall_rate = df["label"].mean()
    print(f"[INFO] 전체 {len(df):,}명 중 라벨(threshold>={label_threshold}) 비율: {overall_rate:.2%}")

    df["decile"] = pd.qcut(df[score_col], n_buckets, labels=False, duplicates="drop")
    summary = df.groupby("decile", observed=True).agg(
        n=(scored_id_col, "size"),
        score_min=(score_col, "min"),
        score_max=(score_col, "max"),
        label_rate=("label", "mean"),
    )
    summary["lift_vs_overall"] = summary["label_rate"] / overall_rate if overall_rate > 0 else float("nan")
    print(summary)

    return df


def main():
    parser = argparse.ArgumentParser(description="스코어 CSV를 실제 라벨(전환 등) CSV와 대조해 구간별 lift를 계산한다.")
    parser.add_argument("--scored", required=True, help="스코어 CSV (id_col + score_col)")
    parser.add_argument("--score-col", required=True)
    parser.add_argument("--scored-id-col", default="req_user_id")
    parser.add_argument("--labels", required=True, help="라벨 CSV (id_col + label_col)")
    parser.add_argument("--label-col", required=True, help="숫자/이진 라벨 컬럼명 (예: max_tier)")
    parser.add_argument("--label-id-col", required=True, help="라벨 CSV의 ID 컬럼명 (스코어와 ID 체계가 다를 수 있음)")
    parser.add_argument("--label-threshold", type=float, default=1.0, help="label_col >= 이 값이면 전환(1)으로 간주")
    parser.add_argument("--id-map", help="scored_id_col <-> label_id_col 매핑 CSV (둘의 ID 체계가 다를 때)")
    parser.add_argument("--map-from-col", help="--id-map에서 scored_id_col에 대응하는 컬럼명")
    parser.add_argument("--map-to-col", help="--id-map에서 label_id_col에 대응하는 컬럼명")
    parser.add_argument("--n-buckets", type=int, default=10, help="스코어를 몇 분위로 나눠볼지 (기본 10 = decile)")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    scored = pd.read_csv(args.scored)
    labels = pd.read_csv(args.labels)
    id_map = pd.read_csv(args.id_map) if args.id_map else None

    result = run_backtest(
        scored=scored,
        labels=labels,
        scored_id_col=args.scored_id_col,
        score_col=args.score_col,
        label_id_col=args.label_id_col,
        label_col=args.label_col,
        label_threshold=args.label_threshold,
        id_map=id_map,
        map_from_col=args.map_from_col,
        map_to_col=args.map_to_col,
        n_buckets=args.n_buckets,
    )
    result.to_csv(args.output, index=False)
    print(f"[INFO] 백테스트 결과 저장: {args.output}")


if __name__ == "__main__":
    main()
