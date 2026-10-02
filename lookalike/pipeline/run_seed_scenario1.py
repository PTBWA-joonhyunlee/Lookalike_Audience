# lookalike/pipeline/run_seed_scenario1.py
#
# 시나리오 1 — 신규 seed 입력부터 top N% 추출까지 Athena를 직접 호출해 한 번에 실행한다.
#
#   0. data/seeds/<seed>/input/<원본>.csv 입력(없으면 --input-csv를 그 위치로 복사)
#   1. S3(prod/lookalike/seeds/<seed>/input/)에 업로드 -> 임시 외부 테이블 생성(끝나면 DROP)
#   2. id_space_check 실행 -> direct/crosswalk 자동 판정(애매하면 중단)
#   3. seed segment 추출(UNLOAD, 테이블 생성 없음) -> 다운로드
#   4. candidate segment 추출(기간별 캐시, 이미 있으면 재사용) -> 다운로드
#   5. seed/pool/candidate 임베딩(기존 Autoencoder, 재학습 없음) -> 분류기 학습(seed=1/pool=0)
#   6. candidate 스코어링(기존 seed 전부 로컬에서 제외) -> top N% 추출
#
# 경로 규칙은 pipeline/paths.py 참고(로컬 data/ 와 s3://ptbwa-dw/prod/lookalike/ 가 같은 상대 경로).
# 단계별 산출물이 이미 있으면 건너뛴다(--force로 재실행). pool은 data/pools/<pool_id>/pool_spec.json.
#
# 실행(lookalike/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m pipeline.run_seed_scenario1 --seed-name je \
#       --period 2026-06-01:2026-09-30 --top-pct 10
#   (--dry-run: AWS 호출/학습 없이 경로와 단계별 상태만 출력)

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from pipeline import athena_queries as aq
from pipeline.athena import Aws
from pipeline.athena_queries import decide_id_space
from pipeline.encode import encode_to, read_embeddings_for_ids
from pipeline.paths import (
    ATHENA_RESULTS_S3,
    LOCAL_ROOT,
    PROJECT_ROOT,
    SCRATCH_DB,
    Layout,
    period_key,
    temp_table_name,
)
from scoring import config as scoring_config
from scoring.infer_lookalike import score
from scoring.train_lookalike import train

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UUID_LINE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
AE_VERSION_LEGACY = "legacy"
ID_COL = scoring_config.ID_COL


# ---------- 입력/설정 확인 ----------

def parse_periods(raw: List[str]) -> List[Tuple[str, str]]:
    periods = []
    for item in raw:
        start, sep, end = item.partition(":")
        if not sep:
            raise ValueError(f"--period는 YYYY-MM-01:YYYY-MM-DD 형식입니다: {item!r}")
        periods.append((date.fromisoformat(start).isoformat(), date.fromisoformat(end).isoformat()))
    return periods


def periods_overlap(a: List[Tuple[str, str]], b: List[Tuple[str, str]]) -> bool:
    return any(s1 <= e2 and s2 <= e1 for s1, e1 in a for s2, e2 in b)


def detect_header(csv_path: Path) -> bool:
    """첫 줄(따옴표/BOM 제거)이 UUID가 아니면 헤더로 본다. 첫 열만 쓴다."""
    with open(csv_path, encoding="utf-8-sig") as f:
        first = f.readline().strip()
    first_col = first.split(",")[0].strip().strip('"')
    if "," in first:
        print(f"[WARN] {csv_path.name}: 열이 여러 개입니다 — 첫 번째 열({first_col!r}...)만 device_ifa로 읽습니다")
    return not UUID_LINE.match(first_col)


def load_pool_spec(pool_id: str) -> dict:
    spec_path = Layout.local(Layout.rel_pool(pool_id)) / "pool_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(
            f"{spec_path}가 없습니다 — pool은 시나리오 2(pool 추출)로 만들거나 pool_spec.json을 직접 작성하세요"
        )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    pool_dir = spec_path.parent
    ae_version = spec.get("ae_version", AE_VERSION_LEGACY)
    spec["periods"] = [tuple(p) for p in spec["periods"]]
    spec["segment_csv"] = PROJECT_ROOT / spec["segment_csv"] if "segment_csv" in spec else pool_dir / "pool_segment.csv"
    spec["embeddings_csv"] = (
        PROJECT_ROOT / spec["embeddings_csv"] if "embeddings_csv" in spec else pool_dir / f"emb_{ae_version}.csv"
    )
    spec["ae_version"] = ae_version
    spec["dir"] = pool_dir
    return spec


def read_ids(csv_path: Path) -> set:
    return set(pd.read_csv(csv_path, usecols=[ID_COL], dtype=str)[ID_COL])


def collect_excluded_ids() -> Tuple[set, List[Path]]:
    """기존 seed 전부(옛 data/seed/seed_segment*.csv + 새 구조 data/seeds/*/*/seed_segment.csv)의
    device_ifa — candidate에서 제외한다. seed 중 skp 세그먼트가 없는 사람은 어차피 candidate가 될 수
    없어(candidate는 skp 세그먼트 보유자만) segment CSV 기준 제외가 기존 seed 테이블 제외와 같다."""
    files = sorted((LOCAL_ROOT / "seed").glob("seed_segment*.csv"))
    files += sorted((LOCAL_ROOT / "seeds").glob("*/*/seed_segment.csv"))
    ids = set()
    for f in files:
        ids |= read_ids(f)
    return ids, files


# ---------- 단계 ----------

class Run:
    def __init__(self, args):
        self.seed = args.seed_name
        self.run_id = args.run_id
        self.force = args.force
        self.top_pct = args.top_pct
        self.periods = parse_periods(args.period)
        self.pool_id = args.pool_id
        self.pool = load_pool_spec(self.pool_id)
        self.ae_version = self.pool["ae_version"]
        if self.ae_version != AE_VERSION_LEGACY:
            raise NotImplementedError(
                f"ae_version={self.ae_version!r}은 아직 지원하지 않습니다(시나리오 2 — 오토인코더 재학습 — 에서 추가)"
            )
        if periods_overlap(self.periods, self.pool["periods"]):
            raise ValueError(
                f"candidate 기간 {self.periods}이 pool(학습) 기간 {self.pool['periods']}과 겹칩니다 — "
                f"CLAUDE.md 규칙: 학습과 후보 기간은 분리해야 합니다"
            )

        self.rel_run = Layout.rel_seed_run(self.seed, self.run_id)
        self.run_dir = Layout.local(self.rel_run)
        self.input_dir = Layout.local(Layout.rel_seed_input(self.seed))
        self.pk = period_key(self.periods)
        self.cand_dir = Layout.local(Layout.rel_candidates(self.periods))

        self.seed_segment_csv = self.run_dir / "seed_segment.csv"
        self.id_space_json = self.run_dir / "id_space_check.json"
        self.seed_emb_csv = self.run_dir / "seed_emb.csv"
        self.model_dir = self.run_dir / "model"
        self.scores_dir = self.run_dir / "scores"
        self.cand_segment_csv = self.cand_dir / "segment.csv"
        self.cand_emb_csv = self.cand_dir / f"emb_{self.ae_version}.csv"
        self.model_pt = self.model_dir / "model.pt"
        self.top_csv = self.scores_dir / f"candidate_scores_top{self.top_pct:g}pct.csv"

        self.s3_input = Layout.s3_uri(Layout.rel_seed_input(self.seed))
        self.s3_seed_segment = Layout.s3_uri(f"{self.rel_run}/seed_segment")
        self.s3_cand_segment = Layout.s3_uri(f"{Layout.rel_candidates(self.periods)}/segment")
        self.temp_table = temp_table_name(self.seed, self.run_id)
        self.aws: Optional[Aws] = None

    def _need(self, path: Path) -> bool:
        return self.force or not path.exists()

    def status(self) -> None:
        print(f"seed={self.seed} run_id={self.run_id} pool={self.pool_id} ae={self.ae_version}")
        print(f"candidate 기간: {self.periods} (period_key={self.pk})")
        rows = [
            ("seed 입력", self.input_dir), ("id_space_check", self.id_space_json),
            ("seed segment", self.seed_segment_csv), ("candidate segment", self.cand_segment_csv),
            ("pool segment", self.pool["segment_csv"]), ("seed 임베딩", self.seed_emb_csv),
            ("pool 임베딩", self.pool["embeddings_csv"]), ("candidate 임베딩", self.cand_emb_csv),
            ("모델", self.model_pt), ("top 결과", self.top_csv),
        ]
        for name, p in rows:
            print(f"  [{'있음' if p.exists() else '없음'}] {name}: {p}")
        print(f"  S3 seed 입력: {self.s3_input}")
        print(f"  S3 seed segment: {self.s3_seed_segment}")
        print(f"  S3 candidate segment: {self.s3_cand_segment}")
        print(f"  Athena 결과 위치: {ATHENA_RESULTS_S3} / 임시 테이블: {SCRATCH_DB}.{self.temp_table}")

    # 0~3
    def stage_seed(self, input_csv: Optional[str]) -> None:
        if not self._need(self.seed_segment_csv) and self.id_space_json.exists():
            print(f"[SKIP] seed segment 이미 있음: {self.seed_segment_csv}")
            return

        src = self._resolve_input(input_csv)
        has_header = detect_header(src)
        print(f"[STEP 1] seed 업로드: {src.name} (헤더 {'있음' if has_header else '없음'}) -> {self.s3_input}")
        self.aws = self.aws or Aws()
        existing = [k for k in self.aws.list_keys(self.s3_input) if not k.endswith("/")]
        s3_key_name = src.name
        stray = [k for k in existing if k.rsplit("/", 1)[-1] != s3_key_name]
        if stray:
            raise RuntimeError(
                f"{self.s3_input}에 다른 파일이 있습니다({stray[:3]}) — 임시 테이블은 이 폴더 전체를 읽으므로 "
                f"seed 입력 파일 하나만 두세요"
            )
        self.aws.upload_file(src, self.s3_input + s3_key_name)

        try:
            self.aws.run_query(aq.render_drop_temp_table(self.temp_table), label="drop-stale")
            self.aws.run_query(aq.render_temp_table_ddl(self.temp_table, self.s3_input, has_header), label="create-temp")

            print("[STEP 2] id_space_check")
            qid, _ = self.aws.run_query(aq.render_id_space_check(self.temp_table), label="id-space")
            row = self.aws.query_rows(qid)[0]
            counts = [int(row[k]) for k in (
                "seed_total", "seed_matches_bidlog", "seed_matches_skp_direct", "seed_matches_skb_ad_id",
                "seed_matches_skb_platform_ad_id", "seed_matches_skb_uuid")]
            decision = decide_id_space(*counts)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.id_space_json.write_text(
                json.dumps({"counts": row, "decision": decision}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[판정] mode={decision['mode']} direct={decision['direct_rate']:.1%} "
                  f"crosswalk={decision['crosswalk_rate']:.1%}({decision['crosswalk_col']}) 근거: {self.id_space_json}")
            if decision["mode"] == "ambiguous":
                raise SystemExit(
                    "[중단] direct/crosswalk 자동 판정 불가 — id_space_check.json을 보고 값 포맷을 직접 확인하세요")

            print("[STEP 3] seed segment 추출(UNLOAD)")
            select_sql = aq.render_seed_segment_query(self.temp_table, decision["mode"], decision["crosswalk_col"])
            self._unload_and_download(select_sql, self.s3_seed_segment, self.seed_segment_csv, "seed-segment")
        finally:
            if self.aws:
                try:
                    self.aws.run_query(aq.render_drop_temp_table(self.temp_table), label="drop-temp")
                except Exception as e:  # DROP 실패가 원래 에러를 가리지 않게
                    print(f"[WARN] 임시 테이블 DROP 실패 — 수동 삭제 필요: {SCRATCH_DB}.{self.temp_table} ({e})")

    def _resolve_input(self, input_csv: Optional[str]) -> Path:
        if input_csv:
            src = Path(input_csv)
            if not src.is_absolute():
                src = PROJECT_ROOT / src
            if not src.exists():
                raise FileNotFoundError(src)
            dst = self.input_dir / src.name
            if src.resolve() != dst.resolve():
                self.input_dir.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(src.read_bytes())
                print(f"[INFO] 입력 복사: {src} -> {dst}")
            return dst
        found = sorted(self.input_dir.glob("*.csv"))
        if len(found) != 1:
            raise FileNotFoundError(
                f"{self.input_dir}에 CSV가 정확히 1개 있어야 합니다(현재 {len(found)}개) — 또는 --input-csv 지정")
        return found[0]

    def _unload_and_download(self, select_sql: str, s3_prefix: str, out_csv: Path, label: str) -> None:
        deleted = self.aws.delete_prefix(s3_prefix)
        if deleted:
            print(f"[INFO] 이전 결과 {deleted}개 삭제: {s3_prefix}")
        self.aws.run_query(aq.render_unload(select_sql, s3_prefix), label=label)
        n = self.aws.download_concat(s3_prefix, out_csv, aq.SEGMENT_HEADER)
        print(f"[OK] {n:,}행 -> {out_csv}")

    # 4
    def stage_candidate(self) -> None:
        if not self._need(self.cand_segment_csv):
            print(f"[SKIP] candidate segment 캐시 있음: {self.cand_segment_csv}")
            return
        print(f"[STEP 4] candidate segment 추출(UNLOAD): {self.periods}")
        self.aws = self.aws or Aws()
        select_sql = aq.render_candidate_segment_query(self.periods)
        self._unload_and_download(select_sql, self.s3_cand_segment, self.cand_segment_csv, "candidate-segment")

    # 5
    def stage_encode(self) -> None:
        print("[STEP 5a] 임베딩(기존 Autoencoder forward)")
        if self._need(self.seed_emb_csv):
            if self.seed_emb_csv.exists():
                self.seed_emb_csv.unlink()
            encode_to(self.seed_segment_csv, f"{self.seed}_{self.run_id}", self.seed_emb_csv)
        pool_emb = self.pool["embeddings_csv"]
        if not pool_emb.exists():
            encode_to(self.pool["segment_csv"], f"pool_{self.pool_id}", pool_emb)
        encode_to(self.cand_segment_csv, f"cand_{hashlib.sha1(self.pk.encode()).hexdigest()[:8]}", self.cand_emb_csv)

    def variant(self) -> scoring_config.Variant:
        return scoring_config.Variant(
            name=f"segment_{self.seed}_{self.run_id}",
            sources=[(self.seed_emb_csv, scoring_config.SEGMENT_EMBED_COLS)],
            artifact_dir=self.model_dir,
            seed_ids_csv=self.seed_segment_csv,
            pool_ids_csv=self.pool["segment_csv"],
            candidate_ids_csv=self.cand_segment_csv,
        )

    # 5b
    def stage_train(self, epochs: int, device: str) -> None:
        if not self._need(self.model_pt):
            print(f"[SKIP] 모델 있음: {self.model_pt}")
            return
        print("[STEP 5b] 분류기 학습")
        variant = self.variant()
        seed_ids = read_ids(self.seed_segment_csv)
        pool_ids = read_ids(self.pool["segment_csv"])
        seed_emb = pd.read_csv(self.seed_emb_csv, dtype={ID_COL: str})
        pool_emb = read_embeddings_for_ids(self.pool["embeddings_csv"], pool_ids - seed_ids)
        print(f"[INFO] 임베딩: seed {len(seed_emb):,} / pool {len(pool_emb):,}")
        embeddings = pd.concat([seed_emb, pool_emb], ignore_index=True).drop_duplicates(subset=[ID_COL], keep="first")
        train(variant, num_epochs=epochs, device=device, embeddings=embeddings)
        (self.model_dir / "config.json").write_text(json.dumps({
            "seed": self.seed, "run_id": self.run_id, "pool_id": self.pool_id, "ae_version": self.ae_version,
            "candidate_period_key": self.pk, "epochs": epochs,
            "n_seed": len(seed_ids), "n_pool": len(pool_ids),
            "trained_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6
    def stage_score(self, device: str) -> None:
        if not self._need(self.top_csv):
            print(f"[SKIP] top 결과 있음: {self.top_csv}")
            return
        print("[STEP 6] 스코어링 (기존 seed 로컬 제외)")
        cand_ids = read_ids(self.cand_segment_csv)
        excluded, files = collect_excluded_ids()
        remaining = cand_ids - excluded
        print(f"[INFO] candidate {len(cand_ids):,} - 기존 seed {len(excluded):,}명({len(files)}개 파일) "
              f"=> 대상 {len(remaining):,}")
        self.scores_dir.mkdir(parents=True, exist_ok=True)
        score(self.variant(), device=device, top_pct=self.top_pct,
              output_path=str(self.scores_dir / "candidate_scores.csv"),
              embeddings_csv=self.cand_emb_csv, candidate_ids=remaining)
        (self.run_dir / "run.json").write_text(json.dumps({
            "seed": self.seed, "run_id": self.run_id, "pool_id": self.pool_id, "ae_version": self.ae_version,
            "candidate_periods": self.periods, "candidate_period_key": self.pk, "top_pct": self.top_pct,
            "n_candidate_after_exclusion": len(remaining), "n_excluded_seed_ids": len(excluded),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[DONE] {self.top_csv}")


STAGES = ["seed", "candidate", "encode", "train", "score"]


def main():
    ap = argparse.ArgumentParser(description="시나리오 1: 신규 seed -> Athena 추출 -> 학습 -> 후보 스코어링 -> top N%")
    ap.add_argument("--seed-name", required=True)
    ap.add_argument("--period", action="append", required=True, metavar="YYYY-MM-01:YYYY-MM-DD",
                    help="candidate 기간(반복 가능)")
    ap.add_argument("--input-csv", help="seed 원본 CSV(기본: data/seeds/<seed>/input/ 안의 CSV 1개)")
    ap.add_argument("--pool-id", default="legacy", help="data/pools/<pool_id>/pool_spec.json (기본: legacy)")
    ap.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--top-pct", type=float, default=10.0)
    ap.add_argument("--epochs", type=int, default=scoring_config.NUM_EPOCHS)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--stop-after", choices=STAGES, help="이 단계까지만 실행")
    ap.add_argument("--force", action="store_true", help="산출물이 있어도 다시 실행")
    ap.add_argument("--dry-run", action="store_true", help="AWS 호출/학습 없이 경로와 단계별 상태만 출력")
    args = ap.parse_args()

    run = Run(args)
    run.status()
    if args.dry_run:
        return

    t0 = time.time()
    steps = {
        "seed": lambda: run.stage_seed(args.input_csv),
        "candidate": run.stage_candidate,
        "encode": run.stage_encode,
        "train": lambda: run.stage_train(args.epochs, args.device),
        "score": lambda: run.stage_score(args.device),
    }
    for name in STAGES:
        steps[name]()
        if args.stop_after == name:
            break
    print(f"[END] {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
