# lookalike/pipeline/run_ae_scenario2.py
#
# 시나리오 2 — pool 조건 입력부터 오토인코더 재학습까지.
#
#   1. pool 조건(추출 기간, 표본 비율, region, OS)을 받아 data/pools/<pool_id>/pool_spec.json에 기록
#   2. pool segment 추출(UNLOAD, 테이블 생성 없음) -> data/pools/<pool_id>/pool_segment.csv
#   3. 오토인코더 학습 -> data/autoencoders/<ae_version>/{model.pt, age_bracket_vocab.json,
#      segment_bert_lookup.npz, config.json}  (config.json = 모델 구조 + 학습 설정 + 결과 + 출처)
#   4. pool을 새 오토인코더로 인코딩 -> data/pools/<pool_id>/emb_<ae_version>.csv
#
# 만들어진 ae_version은 시나리오 1에서 --ae-version으로 고른다(run.json/모델 config에 기록됨).
# 같은 pool_id에 다른 조건으로 다시 추출하는 건 거부한다(pool은 불변 — 새 pool_id를 쓸 것).
#
# 실행(lookalike/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m pipeline.run_ae_scenario2 --pool-id pool_2026-04_05_s5 \
#       --period 2026-04-01:2026-05-31 --sample-pct 5
#   (--explain-only: 쿼리를 Athena EXPLAIN으로 검증만 / --dry-run: AWS 호출·학습 없이 경로·상태만 출력)

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from embedding.segment_features import artifacts
from pipeline import athena_queries as aq
from pipeline import lineage
from pipeline.athena import Aws
from pipeline.encode import encode_to
from pipeline.paths import (
    ATHENA_RESULTS_S3,
    Layout,
    ae_dir as ae_dir_of,
    parse_periods,
)
from train.segment_features import TrainParams, prepare_ae_dir, train_ae, write_config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STAGES = ["pool", "train", "encode"]
SPEC_KEYS = ("periods", "sample_pct", "sample_salt", "region_prefix", "android_only")


class Scenario2:
    def __init__(self, args):
        self.pool_id = args.pool_id
        self.ae_version = args.ae_version or f"ae_{args.pool_id}_{datetime.now().strftime('%Y%m%d')}"
        self.force = args.force
        self.args = args
        self.periods = parse_periods(args.period)

        self.pool_dir = Layout.local(Layout.rel_pool(self.pool_id))
        self.spec_path = self.pool_dir / "pool_spec.json"
        self.pool_segment_csv = self.pool_dir / "pool_segment.csv"
        self.s3_pool_segment = Layout.s3_uri(f"{Layout.rel_pool(self.pool_id)}/segment")
        self.ae_dir = ae_dir_of(self.ae_version)
        self.model_pt = self.ae_dir / artifacts.MODEL_FILE
        self.pool_emb_csv = self.pool_dir / f"emb_{self.ae_version}.csv"
        self.aws = None

        self.spec = {
            "pool_id": self.pool_id,
            "periods": [list(p) for p in self.periods],
            "sample_pct": args.sample_pct,
            "sample_salt": args.sample_salt,
            "region_prefix": args.region,
            "android_only": not args.any_os,
        }

    def sql(self) -> str:
        return aq.render_population_segment_query(
            self.periods, sample_pct=self.spec["sample_pct"], sample_salt=self.spec["sample_salt"],
            region_prefix=self.spec["region_prefix"], android_only=self.spec["android_only"])

    def status(self) -> None:
        print(f"pool_id={self.pool_id} ae_version={self.ae_version}")
        print(f"pool 조건: {json.dumps({k: self.spec[k] for k in SPEC_KEYS}, ensure_ascii=False)}")
        for name, p in [("pool_spec", self.spec_path), ("pool segment", self.pool_segment_csv),
                        ("AE 모델", self.model_pt), ("AE config", self.ae_dir / artifacts.CONFIG_FILE),
                        ("pool 임베딩", self.pool_emb_csv)]:
            print(f"  [{'있음' if p.exists() else '없음'}] {name}: {p}")
        print(f"  S3 pool segment: {self.s3_pool_segment}")
        print(f"  Athena 결과 위치: {ATHENA_RESULTS_S3}")

    def _check_spec_immutable(self) -> None:
        if not self.spec_path.exists():
            return
        old = json.loads(self.spec_path.read_text(encoding="utf-8"))
        diff = {k: (old.get(k), self.spec[k]) for k in SPEC_KEYS if old.get(k) != self.spec[k]}
        if diff and not self.force:
            raise SystemExit(
                f"[중단] pool '{self.pool_id}'는 이미 다른 조건으로 만들어져 있습니다(기존 -> 입력): {diff}\n"
                f"pool은 불변입니다 — 새 --pool-id를 쓰세요(덮어쓰려면 --force)")

    # 1~2
    def stage_pool(self) -> None:
        self._check_spec_immutable()
        if not self.force and self.pool_segment_csv.exists():
            print(f"[SKIP] pool segment 이미 있음: {self.pool_segment_csv}")
            return
        print(f"[STEP 1] pool segment 추출(UNLOAD): {self.periods} 표본 {self.spec['sample_pct']}%")
        self.aws = self.aws or Aws()
        with lineage.Stage(self.pool_dir, "pool_segment") as st:
            st.params = dict(self.spec)
            sql = self.sql()
            sql_ref = lineage.save_sql(self.pool_dir, "pool_segment", sql)
            snapshot = self.aws.skp_snapshot()
            st.inputs = {
                "bid_log": {"table": "prod-ptbwa-dw.abi_bid_log_flatten", "periods": self.spec["periods"],
                            "filters": f"region={self.spec['region_prefix']}*, android_only={self.spec['android_only']}, "
                                       "collect=1, lmt!=1, UUID 형식, skp 세그먼트 보유"},
                "segments": {"table": "propfit.ptbwa_skp", "rule": "ad_id별 최신 레코드(추출 시점 스냅샷 — 기간별 시점 세그먼트가 아님)",
                             "snapshot": snapshot},
            }
            deleted = self.aws.delete_prefix(self.s3_pool_segment)
            if deleted:
                print(f"[INFO] 이전 결과 {deleted}개 삭제: {self.s3_pool_segment}")
            qid, stats = self.aws.run_query(aq.render_unload(sql, self.s3_pool_segment), label="pool-segment")
            st.athena.append(lineage.athena_info(qid, stats, sql_ref, self.s3_pool_segment, "unload pool segment"))
            n = self.aws.download_concat(self.s3_pool_segment, self.pool_segment_csv, aq.SEGMENT_HEADER)
            st.outputs = {"pool_segment": lineage.file_info(self.pool_segment_csv, rows=n)}
            self.spec.update(n_devices=n, extracted_at=datetime.now().isoformat(timespec="seconds"), skp_snapshot=snapshot)
            self.pool_dir.mkdir(parents=True, exist_ok=True)
            self.spec_path.write_text(json.dumps(self.spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] {n:,}행 -> {self.pool_segment_csv}")
        # 학습 메모리 안내: 피처 npz는 행당 약 1.5KB(int64 인덱스 192개)
        print(f"[INFO] 학습 피처 메모리 추정 약 {n * 1.5 / 1e6:.1f}GB")

    def _load_spec(self) -> dict:
        return json.loads(self.spec_path.read_text(encoding="utf-8"))

    # 3
    def stage_train(self) -> None:
        cfg_path = self.ae_dir / artifacts.CONFIG_FILE
        if not self.force and self.model_pt.exists() and cfg_path.exists():
            print(f"[SKIP] 오토인코더 이미 있음: {self.ae_dir}")
            return
        if self.model_pt.exists() and not self.force:
            raise SystemExit(f"[중단] {self.ae_dir}에 model.pt가 있는데 config.json이 없습니다(legacy 모델?) — 다른 --ae-version을 쓰세요")
        print(f"[STEP 2] 오토인코더 학습: {self.ae_version}")
        a = self.args
        pool_spec = self._load_spec()
        with lineage.Stage(self.ae_dir, "train_autoencoder") as st:
            st.inputs = {
                "pool": {"pool_id": self.pool_id, "conditions": {k: pool_spec.get(k) for k in SPEC_KEYS},
                         "skp_snapshot": pool_spec.get("skp_snapshot"), "lineage": lineage.lineage_path(self.pool_dir),
                         "pool_segment": lineage.file_info(self.pool_segment_csv, rows=pool_spec.get("n_devices"))},
                "bert_lookup": "legacy segment_bert_lookup.npz 복사(taxonomy 기준, 데이터 무관)",
            }
            max_rows = a.train_max_rows or None
            npz, data_info = prepare_ae_dir(self.ae_dir, self.pool_segment_csv, max_rows=max_rows, seed=a.seed)
            spec = artifacts.ModelSpec(age_embed_dim=a.age_embed_dim, hidden_dim=a.hidden_dim)
            params = TrainParams(num_epochs=a.epochs, batch_size=a.batch_size, learning_rate=a.lr,
                                 val_split=a.val_split, patience=a.patience, seed=a.seed)
            st.params = {"train": vars(params), "model": spec.to_dict(), "data": data_info}
            result = train_ae(self.ae_dir, npz, params, spec, device=a.device)
            result.update(data_info)
            age_vocab_size = len(artifacts.load_age_vocab(self.ae_dir))
            write_config(self.ae_dir, self.ae_version, spec, result, pool_spec, age_vocab_size)
            st.outputs = {"model": lineage.file_info(self.model_pt), "config": lineage.file_info(cfg_path, hash_content=False),
                          "best_epoch": result["best_epoch"], "best_val_loss": result["best_val_loss"],
                          "epochs_run": result["epochs_run"]}
        npz.unlink(missing_ok=True)   # 파생 파일(수 GB 가능) — pool segment CSV로 언제든 다시 만들 수 있다
        print(f"[OK] {cfg_path}")

    # 4
    def stage_encode(self) -> None:
        print("[STEP 3] pool 인코딩(새 오토인코더)")
        with lineage.Stage(self.pool_dir, "encode_pool") as st:
            st.models = {"autoencoder": artifacts.describe(self.ae_dir, self.ae_version)}
            st.inputs = {"pool_segment": lineage.file_info(self.pool_segment_csv, hash_content=False)}
            n = encode_to(self.pool_segment_csv, f"pool_{self.pool_id}_{self.ae_version}", self.pool_emb_csv, ae_dir=self.ae_dir)
            st.outputs = {"pool_embeddings": lineage.file_info(self.pool_emb_csv), "newly_encoded": n}
        print(f"[OK] {self.pool_emb_csv} (신규 {n:,}명)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="시나리오 2: pool 추출 -> 오토인코더 재학습")
    g = ap.add_argument_group("pool 조건")
    g.add_argument("--pool-id", required=True, help="pool 이름(data/pools/<pool_id>/). 같은 이름에 다른 조건은 거부")
    g.add_argument("--period", action="append", required=True, metavar="YYYY-MM-01:YYYY-MM-DD",
                   help="pool 추출 기간(bid log 활동 기준, 반복 가능). 시작은 월 1일, 같은 연도 안")
    g.add_argument("--sample-pct", type=float, default=5.0,
                   help="device_ifa 해시 표본 비율(%%, 0 초과 100 이하, 0.01%% 단위, 기본 5). 100이면 전수")
    g.add_argument("--sample-salt", default="", help="표본 해시 salt(다른 값이면 다른 표본)")
    g.add_argument("--region", default="KR", help="device_geo_region 접두사(기본 KR)")
    g.add_argument("--any-os", action="store_true", help="Android 필터를 끈다(기본: device_osv가 숫자인 Android만)")
    t = ap.add_argument_group("오토인코더 학습")
    t.add_argument("--ae-version", help="저장 이름(data/autoencoders/<ae_version>/). 기본: ae_<pool_id>_<날짜>")
    t.add_argument("--train-max-rows", type=int, default=3_000_000,
                   help="pool이 이보다 크면 seed 고정 무작위로 이만큼만 학습에 쓴다(0=전체). 행당 약 0.8KB 메모리")
    t.add_argument("--epochs", type=int, default=30)
    t.add_argument("--batch-size", type=int, default=512)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--hidden-dim", type=int, default=64)
    t.add_argument("--age-embed-dim", type=int, default=8)
    t.add_argument("--val-split", type=float, default=0.05, help="재구성 손실 검증 비율")
    t.add_argument("--patience", type=int, default=5, help="val 손실이 이 에폭 동안 안 내려가면 중단")
    t.add_argument("--seed", type=int, default=42)
    t.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--stop-after", choices=STAGES, help="이 단계까지만 실행")
    ap.add_argument("--force", action="store_true", help="산출물이 있어도 다시 실행/다른 조건 덮어쓰기")
    ap.add_argument("--explain-only", action="store_true", help="pool 쿼리를 Athena EXPLAIN으로 검증만(스캔 없음)")
    ap.add_argument("--dry-run", action="store_true", help="AWS 호출/학습 없이 경로와 상태만 출력")
    return ap


def main():
    args = build_parser().parse_args()
    run = Scenario2(args)
    run.status()
    if args.dry_run:
        return
    if args.explain_only:
        aws = Aws()
        qid, _ = aws.run_query(aq.render_explain(run.sql()), label="explain")
        print("[OK] EXPLAIN 통과(구문/권한/테이블 확인, 스캔 없음)")
        return

    t0 = time.time()
    steps = {"pool": run.stage_pool, "train": run.stage_train, "encode": run.stage_encode}
    for name in STAGES:
        steps[name]()
        if args.stop_after == name:
            break
    print(f"[END] {time.time() - t0:.0f}s — 시나리오 1에서 --ae-version {run.ae_version} --pool-id {run.pool_id} 로 사용")


if __name__ == "__main__":
    main()
