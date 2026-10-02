# lookalike/scoring/compare_imbalance.py
#
# 클래스 불균형 처리 방식(train_lookalike.IMBALANCE_MODES) 비교 실험. 같은 데이터/같은 분할에서
# 방식만 바꿔 학습하고, 검증(에폭 선택)과 별도로 떼어둔 test 분할 AUC를 비교한다 — 에폭 선택에 쓴
# 검증 AUC는 최고값을 고르므로 낙관적이다. 양성이 test에 약 100명뿐이라 분할 seed를 여러 번 돌려
# 평균/표준편차로 본다.
#
# 실행(lookalike/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m scoring.compare_imbalance --seed-name je --run-id 20261002

import argparse
import json
import time
from pathlib import Path

import numpy as np

from embedding.common.device import resolve_device
from pipeline.encode import read_embeddings_for_ids
from pipeline.paths import Layout
from pipeline.run_seed_scenario1 import load_pool_spec, read_ids
from . import config
from .train_lookalike import fit

# (이름, fit 인자). baseline은 기존 동작 재현: 복원추출 + 20에폭 고정 + 마지막 에폭 모델.
CONFIGS = [
    ("baseline(sampler, 20ep, 마지막 에폭)", dict(imbalance="sampler", patience=999)),
    ("sampler + early stop", dict(imbalance="sampler", patience=5)),
    ("posweight + early stop", dict(imbalance="posweight", patience=5)),
    ("undersample(20:1) + early stop", dict(imbalance="undersample", patience=5, neg_per_pos=20)),
]


def load_xy(seed_name: str, run_id: str, pool_id: str):
    run_dir = Layout.local(Layout.rel_seed_run(seed_name, run_id))
    pool = load_pool_spec(pool_id)
    seed_ids = read_ids(run_dir / "seed_segment.csv")
    pool_ids = read_ids(pool["segment_csv"])
    import pandas as pd
    seed_emb = pd.read_csv(run_dir / "seed_emb.csv", dtype={config.ID_COL: str})
    pool_emb = read_embeddings_for_ids(pool["embeddings_csv"], pool_ids - seed_ids)
    df = pd.concat([seed_emb[seed_emb[config.ID_COL].isin(seed_ids)], pool_emb], ignore_index=True)
    df = df.drop_duplicates(subset=[config.ID_COL], keep="first")
    y = df[config.ID_COL].isin(seed_ids).to_numpy(dtype=np.float32)
    x = df[config.SEGMENT_EMBED_COLS].to_numpy(dtype=np.float32)
    return x, y


def stratified_split(y: np.ndarray, seed: int, val: float = 0.1, test: float = 0.1):
    rng = np.random.default_rng(seed)
    parts = {"train": [], "val": [], "test": []}
    for label in (0, 1):
        idx = rng.permutation(np.where(y == label)[0])
        n_val, n_test = int(len(idx) * val), int(len(idx) * test)
        parts["val"].append(idx[:n_val])
        parts["test"].append(idx[n_val:n_val + n_test])
        parts["train"].append(idx[n_val + n_test:])
    return {k: np.concatenate(v) for k, v in parts.items()}


def main():
    ap = argparse.ArgumentParser(description="불균형 처리 방식 비교(test AUC, 분할 seed 반복)")
    ap.add_argument("--seed-name", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--pool-id", default="legacy")
    ap.add_argument("--reps", type=int, default=3, help="분할 seed 반복 횟수")
    ap.add_argument("--epochs", type=int, default=config.NUM_EPOCHS)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--cache", help="x/y 캐시 npz 경로(임베딩 재로드가 느릴 때)")
    args = ap.parse_args()

    device = resolve_device(args.device)
    cache = Path(args.cache) if args.cache else None
    if cache and cache.exists():
        z = np.load(cache)
        x, y = z["x"], z["y"]
    else:
        x, y = load_xy(args.seed_name, args.run_id, args.pool_id)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.savez(cache, x=x, y=y)
    print(f"[INFO] 데이터: {len(y):,}명 (seed {int(y.sum())}, pool {int((y == 0).sum()):,}) device={device}")

    results = {name: [] for name, _ in CONFIGS}
    for rep in range(args.reps):
        split = stratified_split(y, seed=rep)
        print(f"\n===== rep {rep}: train {len(split['train']):,} / val {len(split['val']):,} / test {len(split['test']):,} "
              f"(test 양성 {int(y[split['test']].sum())}) =====")
        for name, kw in CONFIGS:
            t0 = time.time()
            res = fit(x, y, split["train"], split["val"], num_epochs=args.epochs, device=device, seed=rep,
                      test_idx=split["test"], verbose=False, **kw)
            res.pop("state_dict")
            res["seconds"] = round(time.time() - t0, 1)
            # baseline은 마지막 에폭 모델이 곧 기존 동작이므로 그 test AUC를 대표값으로 쓴다
            res["test_auc_reported"] = res["test_auc_last"] if kw["patience"] >= 999 else res["test_auc"]
            results[name].append(res)
            print(f"  {name:36s} best_ep={res['best_epoch']:2d} val={res['best_val_auc']:.4f} "
                  f"test={res['test_auc_reported']:.4f} (마지막 에폭 test {res['test_auc_last']:.4f}) {res['seconds']}s")

    print("\n===== 요약 (test AUC, 분할 seed %d회 평균±표준편차) =====" % args.reps)
    for name, runs in results.items():
        t = np.array([r["test_auc_reported"] for r in runs])
        v = np.array([r["best_val_auc"] for r in runs])
        e = np.array([r["best_epoch"] for r in runs])
        print(f"{name:36s} test {t.mean():.4f}±{t.std():.4f} | val(최고) {v.mean():.4f} | best epoch {e.mean():.1f}")

    out = Layout.local(Layout.rel_seed_run(args.seed_name, args.run_id)) / "imbalance_comparison.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {out}")


if __name__ == "__main__":
    main()
