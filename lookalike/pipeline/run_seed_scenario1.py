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

from embedding.segment_features import artifacts
from pipeline import athena_queries as aq
from pipeline import lineage
from pipeline.athena import Aws
from pipeline.athena_queries import decide_id_space
from pipeline.encode import encode_to, read_embeddings_for_ids
from pipeline.paths import (
    AE_VERSION_LEGACY,
    ATHENA_RESULTS_S3,
    LOCAL_ROOT,
    PROJECT_ROOT,
    SCRATCH_DB,
    Layout,
    ae_dir,
    parse_periods,
    period_key,
    periods_overlap,
    temp_table_name,
)
from scoring import config as scoring_config
from scoring.infer_lookalike import score
from scoring.train_lookalike import IMBALANCE_MODES, train
from train.segment_features import git_commit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UUID_LINE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ID_COL = scoring_config.ID_COL


# ---------- 입력/설정 확인 ----------

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
    spec["periods"] = [tuple(p) for p in spec["periods"]]
    spec["segment_csv"] = PROJECT_ROOT / spec["segment_csv"] if "segment_csv" in spec else spec_path.parent / "pool_segment.csv"
    spec["dir"] = spec_path.parent
    return spec


def pool_embeddings_path(pool: dict, ae_version: str) -> Path:
    """pool을 ae_version으로 인코딩한 임베딩 CSV. 시나리오 2 이전의 legacy pool은 기존 통합 임베딩 파일
    (pool_spec.embeddings_csv, ae_version=legacy)을 그대로 가리킨다."""
    if pool.get("embeddings_csv") and pool.get("ae_version") == ae_version:
        return PROJECT_ROOT / pool["embeddings_csv"]
    return pool["dir"] / f"emb_{ae_version}.csv"


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
        self.args = args
        self.ae_version = args.ae_version
        self.ae_dir = ae_dir(self.ae_version)
        if not (self.ae_dir / artifacts.MODEL_FILE).exists():
            raise FileNotFoundError(
                f"오토인코더 {self.ae_version!r}가 없습니다: {self.ae_dir} — 시나리오 2(run_ae_scenario2)로 먼저 학습하세요")
        self.ae_info = artifacts.describe(self.ae_dir, self.ae_version)
        # pool 기본값: 그 오토인코더를 학습한 pool(legacy 모델은 legacy pool)
        self.pool_id = args.pool_id or self.ae_info.get("trained_on_pool") or "legacy"
        self.pool = load_pool_spec(self.pool_id)
        self.pool_emb_csv = pool_embeddings_path(self.pool, self.ae_version)
        self.overlap = periods_overlap(self.periods, self.pool["periods"])
        if self.overlap:
            if not args.allow_overlap:
                raise ValueError(
                    f"candidate 기간 {self.periods}이 pool(학습) 기간 {self.pool['periods']}과 겹칩니다 — "
                    f"CLAUDE.md 규칙: 학습과 후보 기간은 분리해야 합니다(의도한 경우 --allow-overlap)")
            print(f"[WARN] candidate 기간이 pool 기간과 겹칩니다(--allow-overlap) — lineage에 기록합니다")

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

    def bind_ae(self) -> None:
        """이 run_id의 산출물(seed 임베딩, 모델, 점수)은 오토인코더 하나에 묶여 있다 — 다른 오토인코더로
        같은 run_id를 이어 실행하면 임베딩이 섞이므로 거부한다(새 --run-id를 쓸 것)."""
        path = self.run_dir / "ae_binding.json"
        want = {"ae_version": self.ae_version, "model_sha256": self.ae_info["model_sha256"]}
        if path.exists():
            have = json.loads(path.read_text(encoding="utf-8"))
            if have != want:
                raise SystemExit(f"[중단] 이 run({self.run_id})은 오토인코더 {have}로 만들어졌습니다 — 지금은 {want}. "
                                 f"다른 오토인코더로는 새 --run-id를 쓰세요")
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(want, ensure_ascii=False, indent=2), encoding="utf-8")
        with lineage.Stage(self.run_dir, "run_context") as st:
            st.params = {"seed": self.seed, "run_id": self.run_id, "candidate_periods": self.periods,
                         "top_pct": self.top_pct, "period_overlap_with_pool": self.overlap,
                         "period_overlap_allowed": bool(self.args.allow_overlap)}
            st.models = {"autoencoder": self.ae_info}
            st.inputs = {"pool": {"pool_id": self.pool_id, "periods": self.pool["periods"],
                                  "conditions": {k: self.pool.get(k) for k in
                                                 ("sample_pct", "sample_salt", "region_prefix", "android_only", "note")},
                                  "n_devices": self.pool.get("n_devices"), "skp_snapshot": self.pool.get("skp_snapshot"),
                                  "lineage": lineage.lineage_path(self.pool["dir"])},
                         "autoencoder_lineage": lineage.lineage_path(self.ae_dir),
                         "candidate_cache": lineage.lineage_path(self.cand_dir)}

    def _need(self, path: Path) -> bool:
        return self.force or not path.exists()

    def status(self) -> None:
        print(f"seed={self.seed} run_id={self.run_id} pool={self.pool_id} ae={self.ae_version} "
              f"(model {self.ae_info['model_sha256']}, 학습 pool={self.ae_info.get('trained_on_pool')})")
        print(f"candidate 기간: {self.periods} (period_key={self.pk})")
        rows = [
            ("seed 입력", self.input_dir), ("id_space_check", self.id_space_json),
            ("seed segment", self.seed_segment_csv), ("candidate segment", self.cand_segment_csv),
            ("pool segment", self.pool["segment_csv"]), ("seed 임베딩", self.seed_emb_csv),
            ("pool 임베딩", self.pool_emb_csv), ("candidate 임베딩", self.cand_emb_csv),
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

        with lineage.Stage(self.run_dir, "seed_segment") as st:
            st.inputs = {"seed_list": lineage.file_info(src, rows=lineage.count_rows(src, header=has_header)),
                         "s3_input": self.s3_input + s3_key_name,
                         "segments": {"table": "propfit.ptbwa_skp", "rule": "ad_id별 최신 레코드(추출 시점 스냅샷)",
                                      "snapshot": self.aws.skp_snapshot()}}
            try:
                self.aws.run_query(aq.render_drop_temp_table(self.temp_table), label="drop-stale")
                self.aws.run_query(aq.render_temp_table_ddl(self.temp_table, self.s3_input, has_header), label="create-temp")

                print("[STEP 2] id_space_check")
                sql = aq.render_id_space_check(self.temp_table)
                qid, stats = self.aws.run_query(sql, label="id-space")
                st.athena.append(lineage.athena_info(
                    qid, stats, lineage.save_sql(self.run_dir, "id_space_check", sql), label="id_space_check"))
                row = self.aws.query_rows(qid)[0]
                counts = [int(row[k]) for k in (
                    "seed_total", "seed_matches_bidlog", "seed_matches_skp_direct", "seed_matches_skb_ad_id",
                    "seed_matches_skb_platform_ad_id", "seed_matches_skb_uuid")]
                decision = decide_id_space(*counts)
                self.run_dir.mkdir(parents=True, exist_ok=True)
                self.id_space_json.write_text(
                    json.dumps({"counts": row, "decision": decision}, ensure_ascii=False, indent=2), encoding="utf-8")
                st.params = {"id_space_mode": decision["mode"], "direct_rate": decision["direct_rate"],
                             "crosswalk_rate": decision["crosswalk_rate"], "id_space_counts": row}
                print(f"[판정] mode={decision['mode']} direct={decision['direct_rate']:.1%} "
                      f"crosswalk={decision['crosswalk_rate']:.1%}({decision['crosswalk_col']}) 근거: {self.id_space_json}")
                if decision["mode"] == "ambiguous":
                    raise SystemExit(
                        "[중단] direct/crosswalk 자동 판정 불가 — id_space_check.json을 보고 값 포맷을 직접 확인하세요")

                print("[STEP 3] seed segment 추출(UNLOAD)")
                select_sql = aq.render_seed_segment_query(self.temp_table, decision["mode"], decision["crosswalk_col"])
                info, n = self._unload_and_download(self.run_dir, "seed_segment", select_sql, self.s3_seed_segment,
                                                    self.seed_segment_csv, "seed-segment")
                st.athena.append(info)
                st.outputs = {"seed_segment": lineage.file_info(self.seed_segment_csv, rows=n),
                              "id_space_check": lineage.file_info(self.id_space_json)}
            finally:
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

    def _unload_and_download(self, owner_dir, name: str, select_sql: str, s3_prefix: str, out_csv: Path, label: str):
        """UNLOAD 실행 + 다운로드. 반환: (lineage용 athena 정보, 행 수)."""
        deleted = self.aws.delete_prefix(s3_prefix)
        if deleted:
            print(f"[INFO] 이전 결과 {deleted}개 삭제: {s3_prefix}")
        sql = aq.render_unload(select_sql, s3_prefix)
        qid, stats = self.aws.run_query(sql, label=label)
        info = lineage.athena_info(qid, stats, lineage.save_sql(owner_dir, name, sql), s3_prefix, f"unload {name}")
        n = self.aws.download_concat(s3_prefix, out_csv, aq.SEGMENT_HEADER)
        print(f"[OK] {n:,}행 -> {out_csv}")
        return info, n

    # 4
    def stage_candidate(self) -> None:
        cand_lineage = lineage.lineage_path(self.cand_dir)
        if not self._need(self.cand_segment_csv):
            print(f"[SKIP] candidate segment 캐시 있음: {self.cand_segment_csv}")
            reused = True
        else:
            reused = False
            print(f"[STEP 4] candidate segment 추출(UNLOAD): {self.periods}")
            self.aws = self.aws or Aws()
            with lineage.Stage(self.cand_dir, "candidate_segment") as st:
                st.params = {"periods": self.periods, "region_prefix": "KR", "android_only": True, "sample_pct": None}
                st.inputs = {
                    "bid_log": {"table": "prod-ptbwa-dw.abi_bid_log_flatten", "periods": self.periods,
                                "filters": "region=KR*, Android, collect=1, lmt!=1, UUID 형식, skp 세그먼트 보유"},
                    "segments": {"table": "propfit.ptbwa_skp", "rule": "ad_id별 최신 레코드(추출 시점 스냅샷 — 기간별 시점 세그먼트가 아님)",
                                 "snapshot": self.aws.skp_snapshot()}}
                info, n = self._unload_and_download(self.cand_dir, "candidate_segment",
                                                    aq.render_candidate_segment_query(self.periods),
                                                    self.s3_cand_segment, self.cand_segment_csv, "candidate-segment")
                st.athena.append(info)
                st.outputs = {"candidate_segment": lineage.file_info(self.cand_segment_csv, rows=n)}
        with lineage.Stage(self.run_dir, "candidate_segment_ref") as st:
            st.params = {"periods": self.periods, "cache_reused": reused}
            st.inputs = {"candidate_cache_lineage": cand_lineage,
                         "candidate_segment": lineage.file_info(self.cand_segment_csv, hash_content=False)}

    # 5
    def stage_encode(self) -> None:
        print(f"[STEP 5a] 임베딩(오토인코더 {self.ae_version})")
        with lineage.Stage(self.run_dir, "encode") as st:
            st.models = {"autoencoder": self.ae_info}
            st.inputs = {"seed_segment": lineage.file_info(self.seed_segment_csv, hash_content=False),
                         "pool_segment": lineage.file_info(self.pool["segment_csv"], hash_content=False),
                         "candidate_segment": lineage.file_info(self.cand_segment_csv, hash_content=False)}
            if self._need(self.seed_emb_csv):
                if self.seed_emb_csv.exists():
                    self.seed_emb_csv.unlink()
                encode_to(self.seed_segment_csv, f"{self.seed}_{self.run_id}", self.seed_emb_csv, ae_dir=self.ae_dir)
            if not self.pool_emb_csv.exists():
                encode_to(self.pool["segment_csv"], f"pool_{self.pool_id}_{self.ae_version}", self.pool_emb_csv,
                          ae_dir=self.ae_dir)
            n_cand = encode_to(self.cand_segment_csv,
                               f"cand_{hashlib.sha1(self.pk.encode()).hexdigest()[:8]}_{self.ae_version}",
                               self.cand_emb_csv, ae_dir=self.ae_dir)
            st.outputs = {"seed_embeddings": lineage.file_info(self.seed_emb_csv),
                          "pool_embeddings": lineage.file_info(self.pool_emb_csv, hash_content=False),
                          "candidate_embeddings": lineage.file_info(self.cand_emb_csv),
                          "candidate_newly_encoded": n_cand}

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
    def stage_train(self) -> None:
        if not self._need(self.model_pt):
            print(f"[SKIP] 모델 있음: {self.model_pt}")
            return
        a = self.args
        print(f"[STEP 5b] 분류기 학습 (imbalance={a.imbalance})")
        with lineage.Stage(self.run_dir, "train_classifier") as st:
            variant = self.variant()
            seed_ids = read_ids(self.seed_segment_csv)
            pool_ids = read_ids(self.pool["segment_csv"])
            st.models = {"autoencoder": self.ae_info}
            st.inputs = {"seed_segment": lineage.file_info(self.seed_segment_csv, hash_content=False),
                         "pool": {"pool_id": self.pool_id, "lineage": lineage.lineage_path(self.pool["dir"]),
                                  "pool_segment": lineage.file_info(self.pool["segment_csv"], hash_content=False),
                                  "n_pool_ids": len(pool_ids)},
                         "seed_embeddings": lineage.file_info(self.seed_emb_csv, hash_content=False),
                         "pool_embeddings": lineage.file_info(self.pool_emb_csv, hash_content=False)}
            seed_emb = pd.read_csv(self.seed_emb_csv, dtype={ID_COL: str})
            pool_emb = read_embeddings_for_ids(self.pool_emb_csv, pool_ids - seed_ids)
            print(f"[INFO] 임베딩: seed {len(seed_emb):,} / pool {len(pool_emb):,}")
            embeddings = pd.concat([seed_emb, pool_emb], ignore_index=True).drop_duplicates(subset=[ID_COL], keep="first")
            result = train(variant, num_epochs=a.epochs, batch_size=a.batch_size, lr=a.lr, val_split=a.val_split,
                           device=a.device, seed=a.train_seed, embeddings=embeddings, imbalance=a.imbalance,
                           patience=a.patience, weight_decay=a.weight_decay)
            cfg_path = self.model_dir / "config.json"
            cfg_path.write_text(json.dumps({
                "seed": self.seed, "run_id": self.run_id, "pool_id": self.pool_id,
                "pool": {k: v for k, v in self.pool.items() if k not in ("dir", "segment_csv")},
                "candidate_period_key": self.pk,
                "autoencoder": self.ae_info,     # 이 분류기의 입력 임베딩을 만든 오토인코더
                "classifier_train": result,
                "trained_at": datetime.now().isoformat(timespec="seconds"),
                "git_commit": git_commit(),
            }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            st.params = {k: v for k, v in result.items() if k != "history"}
            st.outputs = {"classifier": lineage.file_info(self.model_pt), "config": lineage.file_info(cfg_path, hash_content=False)}

    # 6
    def stage_score(self) -> None:
        device = self.args.device
        if not self._need(self.top_csv):
            print(f"[SKIP] top 결과 있음: {self.top_csv}")
            return
        print("[STEP 6] 스코어링 (기존 seed 로컬 제외)")
        with lineage.Stage(self.run_dir, "score") as st:
            cand_ids = read_ids(self.cand_segment_csv)
            excluded, files = collect_excluded_ids()
            remaining = cand_ids - excluded
            print(f"[INFO] candidate {len(cand_ids):,} - 기존 seed {len(excluded):,}명({len(files)}개 파일) "
                  f"=> 대상 {len(remaining):,}")
            st.models = {"autoencoder": self.ae_info,
                         "classifier": {"model": lineage.file_info(self.model_pt),
                                        "config": lineage.file_info(self.model_dir / "config.json", hash_content=False)}}
            st.inputs = {"candidate_embeddings": lineage.file_info(self.cand_emb_csv, hash_content=False),
                         "candidate_periods": self.periods,
                         "excluded_seed_files": [lineage._rel(f) for f in files], "n_excluded_seed_ids": len(excluded)}
            st.params = {"top_pct": self.top_pct, "n_candidate": len(cand_ids), "n_scored": len(remaining)}
            self.scores_dir.mkdir(parents=True, exist_ok=True)
            score(self.variant(), device=device, top_pct=self.top_pct,
                  output_path=str(self.scores_dir / "candidate_scores.csv"),
                  embeddings_csv=self.cand_emb_csv, candidate_ids=remaining)
            st.outputs = {"candidate_scores": lineage.file_info(self.scores_dir / "candidate_scores.csv", hash_content=False),
                          "top": lineage.file_info(self.top_csv, rows=lineage.count_rows(self.top_csv))}
        (self.run_dir / "run.json").write_text(json.dumps({
            "seed": self.seed, "run_id": self.run_id, "pool_id": self.pool_id, "ae_version": self.ae_version,
            "autoencoder": self.ae_info, "classifier_config": str(self.model_dir / "config.json"),
            "candidate_periods": self.periods, "candidate_period_key": self.pk, "top_pct": self.top_pct,
            "period_overlap_with_pool": self.overlap, "lineage": lineage.lineage_path(self.run_dir),
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
    ap.add_argument("--ae-version", default=AE_VERSION_LEGACY,
                    help="임베딩에 쓸 오토인코더(data/autoencoders/<ae_version>/, 시나리오 2 산출물). 기본: legacy")
    ap.add_argument("--pool-id", help="data/pools/<pool_id>/pool_spec.json (기본: 그 오토인코더를 학습한 pool, legacy는 legacy)")
    ap.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--top-pct", type=float, default=10.0)
    c = ap.add_argument_group("분류기 학습")
    c.add_argument("--epochs", type=int, default=scoring_config.NUM_EPOCHS)
    c.add_argument("--batch-size", type=int, default=scoring_config.BATCH_SIZE)
    c.add_argument("--lr", type=float, default=scoring_config.LEARNING_RATE)
    c.add_argument("--val-split", type=float, default=scoring_config.VAL_SPLIT)
    c.add_argument("--imbalance", choices=IMBALANCE_MODES, default="posweight",
                   help="클래스 불균형 처리(eda/docs/classifier_imbalance_comparison.md)")
    c.add_argument("--patience", type=int, default=5)
    c.add_argument("--weight-decay", type=float, default=0.0)
    c.add_argument("--train-seed", type=int, default=42)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--stop-after", choices=STAGES, help="이 단계까지만 실행")
    ap.add_argument("--allow-overlap", action="store_true", help="후보 기간이 pool 기간과 겹쳐도 허용(lineage에 기록)")
    ap.add_argument("--force", action="store_true", help="산출물이 있어도 다시 실행")
    ap.add_argument("--dry-run", action="store_true", help="AWS 호출/학습 없이 경로와 단계별 상태만 출력")
    args = ap.parse_args()

    run = Run(args)
    run.status()
    if args.dry_run:
        return
    run.bind_ae()

    t0 = time.time()
    steps = {
        "seed": lambda: run.stage_seed(args.input_csv),
        "candidate": run.stage_candidate,
        "encode": run.stage_encode,
        "train": run.stage_train,
        "score": run.stage_score,
    }
    for name in STAGES:
        steps[name]()
        if args.stop_after == name:
            break
    print(f"[END] {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
