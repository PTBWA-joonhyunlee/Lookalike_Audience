# lookalike/pipeline/run_seed_table_multilabel.py
#
# 시나리오 1의 변형 — seed가 로컬 CSV가 아니라 Athena에 이미 올라가 있는 테이블이고, seed가 여러 개이며,
# 분류기가 멀티라벨(seed 하나당 sigmoid 헤드 하나, 공유 trunk)이다. 임시 테이블/업로드가 필요 없다.
#
#   1. seed별: Athena 테이블(--seed 라벨=DB.테이블:컬럼) -> id_space_check(직접/크로스워크 자동 판정)
#              -> seed segment 추출(UNLOAD) -> 다운로드
#   2. candidate segment 추출(기간별 캐시 재사용) -> seed/pool/candidate 임베딩(--ae-version)
#   3. 멀티라벨 분류기 학습(라벨=seed, pool=전부 0) -> candidate 스코어링(seed별 점수 열)
#   4. 상위 N% 선택: 모든 seed에 같은 pct를 주되 --target-union이 있으면 합집합이 그 크기에 가장 가까운
#      pct를 이분 탐색. --report-pcts별로 seed 간 교집합 표를 만든다.
#
# 경로: data/seeds/<group>/<run_id>/ (seed_segments/<라벨>.csv, id_space_check_<라벨>.json, model/, scores/).
# 경로/lineage/오토인코더 고정 규칙은 시나리오 1과 같다(run_seed_scenario1.Run 상속).
#
# 실행(lookalike/ 안에서):
#   ..\.venv\Scripts\python.exe -m pipeline.run_seed_table_multilabel --group sepo_ctv \
#       --seed sepo_17177=dev-ptbwa-da.sepo_17177:adid --seed sepo_17179=dev-ptbwa-da.sepo_17179:adid \
#       --ae-version ae_2024-09_2026-09_s30 --period 2026-03-01:2026-09-30 --allow-overlap --target-union 1500000

import argparse
import json
import re
import sys
import time
from argparse import Namespace
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pipeline import athena_queries as aq
from pipeline import lineage
from pipeline.athena import Aws
from pipeline.athena_queries import decide_id_space
from pipeline.encode import encode_to, read_embeddings_for_ids
from pipeline.paths import AE_VERSION_LEGACY, SCRATCH_DB, Layout
from pipeline.run_seed_scenario1 import Run, collect_excluded_ids, read_ids
from scoring import config as scoring_config
from scoring.multilabel import find_pct_for_union, score_multilabel, top_masks, train_multilabel
from train.segment_features import git_commit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ID_COL = scoring_config.ID_COL
_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")
ID_CHECK_KEYS = ("seed_total", "seed_matches_bidlog", "seed_matches_skp_direct", "seed_matches_skb_ad_id",
                 "seed_matches_skb_platform_ad_id", "seed_matches_skb_uuid")


class SeedTable:
    def __init__(self, label: str, database: str, table: str, column: str):
        for what, v in (("라벨", label), ("database", database), ("table", table)):
            if not _PART_RE.match(v):
                raise ValueError(f"{what} 형식이 올바르지 않습니다: {v!r}")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", column):
            raise ValueError(f"컬럼 형식이 올바르지 않습니다: {column!r}")
        self.label, self.database, self.table, self.column = label, database, table, column

    @classmethod
    def parse(cls, spec: str) -> "SeedTable":
        """'라벨=DB.테이블:컬럼' (예: sepo_17177=dev-ptbwa-da.sepo_17177:adid)"""
        m = re.match(r"^([^=]+)=([^.:]+)\.([^:]+):(.+)$", spec)
        if not m:
            raise ValueError(f"--seed는 '라벨=DB.테이블:컬럼' 형식입니다: {spec!r}")
        return cls(*m.groups())

    @property
    def ref(self) -> str:
        return f'"{self.database}"."{self.table}"'


class MultiRun(Run):
    def __init__(self, args, seeds: List[SeedTable]):
        if len({s.label for s in seeds}) != len(seeds):
            raise ValueError("--seed 라벨이 중복됩니다")
        args.seed_name = args.group
        args.top_pct = 100.0     # 부모 필드용(이 실행기는 pct를 --target-union/--top-pct로 따로 정한다)
        super().__init__(args)
        self.seeds = seeds
        self.labels = [s.label for s in seeds]
        self.seed_dir = self.run_dir / "seed_segments"
        self.seed_emb_csv = self.run_dir / "seed_emb.csv"
        self.model_pt = self.model_dir / "model_multilabel.pt"
        self.report_pcts = [float(p) for p in args.report_pcts.split(",")] if args.report_pcts else []
        self.union_csv = self.scores_dir / "union_top.csv"

    def seg_csv(self, s: SeedTable) -> Path:
        return self.seed_dir / f"{s.label}.csv"

    def id_json(self, s: SeedTable) -> Path:
        return self.run_dir / f"id_space_check_{s.label}.json"

    def status(self) -> None:
        print(f"group={self.seed} run_id={self.run_id} pool={self.pool_id} ae={self.ae_version} "
              f"(model {self.ae_info['model_sha256']}, 학습 pool={self.ae_info.get('trained_on_pool')})")
        print(f"candidate 기간: {self.periods} (period_key={self.pk})  pool 기간과 겹침: {self.overlap}")
        for s in self.seeds:
            print(f"  seed {s.label}: {s.ref}.{s.column}  segment [{'있음' if self.seg_csv(s).exists() else '없음'}]")
        for name, p in [("candidate segment", self.cand_segment_csv), ("pool segment", self.pool["segment_csv"]),
                        ("seed 임베딩", self.seed_emb_csv), ("candidate 임베딩", self.cand_emb_csv),
                        ("pool 임베딩", self.pool_emb_csv), ("모델", self.model_pt), ("합집합 결과", self.union_csv)]:
            print(f"  [{'있음' if p.exists() else '없음'}] {name}: {p}")

    # 1
    def stage_seed(self, _unused=None) -> None:
        self.aws = self.aws or Aws()
        self.seed_dir.mkdir(parents=True, exist_ok=True)
        for s in self.seeds:
            if not self._need(self.seg_csv(s)) and self.id_json(s).exists():
                print(f"[SKIP] seed segment 이미 있음: {self.seg_csv(s)}")
                continue
            print(f"[STEP 1] seed {s.label}: {s.ref}.{s.column}")
            with lineage.Stage(self.run_dir, f"seed_segment:{s.label}") as st:
                st.inputs = {"seed_table": {"table": s.ref, "column": s.column, "kind": "Athena 기존 테이블(복사/임시 테이블 없음)"},
                             "segments": {"table": "propfit.ptbwa_skp", "rule": "ad_id별 최신 레코드(추출 시점 스냅샷)",
                                          "snapshot": self.aws.skp_snapshot()}}
                sql = aq.render_id_space_check(source_ref=s.ref, col=s.column, uuid_only=False)
                qid, stats = self.aws.run_query(sql, label=f"id-space-{s.label}")
                st.athena.append(lineage.athena_info(
                    qid, stats, lineage.save_sql(self.run_dir, f"id_space_check_{s.label}", sql), label="id_space_check"))
                row = self.aws.query_rows(qid)[0]
                decision = decide_id_space(*[int(row[k]) for k in ID_CHECK_KEYS])
                mode, cw_col = decision["mode"], decision["crosswalk_col"]
                if self.args.id_mode:
                    mode, _, forced_col = self.args.id_mode.partition(":")
                    cw_col = forced_col or cw_col
                    print(f"[INFO] --id-mode로 판정을 덮어씀: mode={mode} crosswalk_col={cw_col}")
                self.id_json(s).write_text(json.dumps(
                    {"counts": row, "decision": decision, "used": {"mode": mode, "crosswalk_col": cw_col}},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                st.params = {"id_space_mode": mode, "crosswalk_col": cw_col if mode == "crosswalk" else None,
                             "direct_rate": decision["direct_rate"], "crosswalk_rate": decision["crosswalk_rate"],
                             "id_space_counts": row, "id_mode_forced": self.args.id_mode}
                print(f"[판정] {s.label}: mode={decision['mode']} direct={decision['direct_rate']:.1%} "
                      f"crosswalk={decision['crosswalk_rate']:.1%}({decision['crosswalk_col']}) "
                      f"seed_total={row['seed_total']} uuid형식={row['seed_uuid_format']}")
                if mode not in ("direct", "crosswalk"):
                    raise SystemExit(f"[중단] {s.label}: direct/crosswalk 자동 판정 불가 — {self.id_json(s)}를 보고 "
                                     f"--id-mode direct 또는 crosswalk:uuid / crosswalk:platform_ad_id 로 지정하세요")
                select_sql = aq.render_seed_segment_query(mode=mode, crosswalk_col=cw_col, source_ref=s.ref,
                                                          col=s.column, uuid_only=False)
                s3_prefix = Layout.s3_uri(f"{self.rel_run}/seed_segment_{s.label}")
                info, n = self._unload_and_download(self.run_dir, f"seed_segment_{s.label}", select_sql, s3_prefix,
                                                    self.seg_csv(s), f"seed-segment-{s.label}")
                st.athena.append(info)
                st.outputs = {"seed_segment": lineage.file_info(self.seg_csv(s), rows=n),
                              "id_space_check": lineage.file_info(self.id_json(s))}

    # 2
    def stage_encode(self) -> None:
        print(f"[STEP 2] 임베딩(오토인코더 {self.ae_version})")
        with lineage.Stage(self.run_dir, "encode") as st:
            st.models = {"autoencoder": self.ae_info}
            st.inputs = {**{f"seed_segment:{s.label}": lineage.file_info(self.seg_csv(s), hash_content=False) for s in self.seeds},
                         "pool_segment": lineage.file_info(self.pool["segment_csv"], hash_content=False),
                         "candidate_segment": lineage.file_info(self.cand_segment_csv, hash_content=False)}
            if self._need(self.seed_emb_csv):
                self.seed_emb_csv.unlink(missing_ok=True)
            for s in self.seeds:     # 같은 dst에 append — 두 seed에 공통인 ID는 한 번만 인코딩된다
                encode_to(self.seg_csv(s), f"{self.seed}_{self.run_id}_{s.label}", self.seed_emb_csv, ae_dir=self.ae_dir)
            if not self.pool_emb_csv.exists():
                encode_to(self.pool["segment_csv"], f"pool_{self.pool_id}_{self.ae_version}", self.pool_emb_csv,
                          ae_dir=self.ae_dir)
            import hashlib
            n_cand = encode_to(self.cand_segment_csv,
                               f"cand_{hashlib.sha1(self.pk.encode()).hexdigest()[:8]}_{self.ae_version}",
                               self.cand_emb_csv, ae_dir=self.ae_dir)
            st.outputs = {"seed_embeddings": lineage.file_info(self.seed_emb_csv),
                          "pool_embeddings": lineage.file_info(self.pool_emb_csv, hash_content=False),
                          "candidate_embeddings": lineage.file_info(self.cand_emb_csv),
                          "candidate_newly_encoded": n_cand}

    # 3
    def stage_train(self) -> None:
        if not self._need(self.model_pt):
            print(f"[SKIP] 모델 있음: {self.model_pt}")
            return
        a = self.args
        print("[STEP 3] 멀티라벨 분류기 학습")
        with lineage.Stage(self.run_dir, "train_classifier_multilabel") as st:
            seed_ids = {s.label: read_ids(self.seg_csv(s)) for s in self.seeds}
            all_seed = set().union(*seed_ids.values())
            pool_ids = read_ids(self.pool["segment_csv"]) - all_seed
            st.models = {"autoencoder": self.ae_info}
            st.inputs = {**{f"seed_segment:{s.label}": lineage.file_info(self.seg_csv(s), hash_content=False) for s in self.seeds},
                         "pool": {"pool_id": self.pool_id, "lineage": lineage.lineage_path(self.pool["dir"]),
                                  "pool_segment": lineage.file_info(self.pool["segment_csv"], hash_content=False),
                                  "n_pool_ids_after_seed_removal": len(pool_ids)},
                         "seed_embeddings": lineage.file_info(self.seed_emb_csv, hash_content=False),
                         "pool_embeddings": lineage.file_info(self.pool_emb_csv, hash_content=False)}
            seed_emb = pd.read_csv(self.seed_emb_csv, dtype={ID_COL: str})
            pool_emb = read_embeddings_for_ids(self.pool_emb_csv, pool_ids)
            emb = pd.concat([seed_emb, pool_emb], ignore_index=True).drop_duplicates(subset=[ID_COL], keep="first")
            emb = emb[emb[ID_COL].isin(all_seed | pool_ids)].reset_index(drop=True)
            Y = np.stack([emb[ID_COL].isin(seed_ids[l]).to_numpy() for l in self.labels], axis=1).astype(np.float32)
            print(f"[INFO] 학습 대상 {len(emb):,}명 (seed별 양성 {dict(zip(self.labels, Y.sum(axis=0).astype(int)))}, "
                  f"둘 이상 겹침 {int((Y.sum(axis=1) > 1).sum())})")
            self.model_dir.mkdir(parents=True, exist_ok=True)
            result = train_multilabel(
                emb[scoring_config.SEGMENT_EMBED_COLS].to_numpy(dtype=np.float32), Y, self.labels, self.model_pt,
                num_epochs=a.epochs, batch_size=a.batch_size, lr=a.lr, val_split=a.val_split,
                weight_decay=a.weight_decay, patience=a.patience, device=a.device, seed=a.train_seed)
            cfg_path = self.model_dir / "config.json"
            cfg_path.write_text(json.dumps({
                "group": self.seed, "run_id": self.run_id, "seeds": [vars(s) for s in self.seeds],
                "pool_id": self.pool_id, "pool": {k: v for k, v in self.pool.items() if k not in ("dir", "segment_csv")},
                "candidate_period_key": self.pk, "autoencoder": self.ae_info, "classifier_train": result,
                "trained_at": datetime.now().isoformat(timespec="seconds"), "git_commit": git_commit(),
            }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            st.params = {k: v for k, v in result.items() if k != "history"}
            st.outputs = {"classifier": lineage.file_info(self.model_pt), "config": lineage.file_info(cfg_path, hash_content=False)}

    # 4
    def stage_score(self) -> None:
        if not self._need(self.union_csv):
            print(f"[SKIP] 합집합 결과 있음: {self.union_csv}")
            return
        a = self.args
        print("[STEP 4] 스코어링 + 상위 N% + 교집합")
        with lineage.Stage(self.run_dir, "score_multilabel") as st:
            cand_ids = read_ids(self.cand_segment_csv)
            excluded, files = collect_excluded_ids()
            this_run = set().union(*[read_ids(self.seg_csv(s)) for s in self.seeds])
            excluded |= this_run
            remaining = cand_ids - excluded
            print(f"[INFO] candidate {len(cand_ids):,} - 제외 seed {len(excluded):,}명(기존 {len(files)}개 파일 + 이번 seed) "
                  f"=> 대상 {len(remaining):,}")
            st.models = {"autoencoder": self.ae_info,
                         "classifier": {"model": lineage.file_info(self.model_pt),
                                        "config": lineage.file_info(self.model_dir / "config.json", hash_content=False)}}
            st.inputs = {"candidate_embeddings": lineage.file_info(self.cand_emb_csv, hash_content=False),
                         "candidate_periods": self.periods, "excluded_seed_files": [lineage._rel(f) for f in files],
                         "n_excluded_seed_ids": len(excluded)}

            df = score_multilabel(self.model_pt, self.cand_emb_csv, remaining, device=a.device)
            self.scores_dir.mkdir(parents=True, exist_ok=True)
            score_cols = [f"score_{l}" for l in self.labels]
            scores = df[score_cols].to_numpy(dtype=np.float32)
            n = len(df)
            all_path = self.scores_dir / "candidate_scores.csv"
            df.to_csv(all_path, index=False)

            if a.target_union:
                pct = find_pct_for_union(scores, a.target_union)
                how = f"합집합 {a.target_union:,}에 가장 가까운 공통 상위 pct 이분 탐색"
            else:
                pct, how = a.top_pct, "--top-pct 고정"
            masks = top_masks(scores, pct)
            union = masks.any(axis=1)
            out = df[union].copy()
            for k, l in enumerate(self.labels):
                out[f"in_{l}"] = masks[union, k].astype(int)
            out = out.sort_values(score_cols, ascending=False)
            out.to_csv(self.union_csv, index=False)
            for k, l in enumerate(self.labels):
                df[masks[:, k]].sort_values(score_cols[k], ascending=False)[[ID_COL, score_cols[k]]].to_csv(
                    self.scores_dir / f"top_{l}.csv", index=False)
            print(f"[INFO] 공통 상위 {pct:.3f}% ({how}) -> seed별 {int(masks[:, 0].sum()):,}명, 합집합 {int(union.sum()):,}명")

            overlap = []
            for p in self.report_pcts:
                m = top_masks(scores, p)
                for i, j in combinations(range(len(self.labels)), 2):
                    inter = int((m[:, i] & m[:, j]).sum())
                    size_i, size_j = int(m[:, i].sum()), int(m[:, j].sum())
                    overlap.append({"top_pct": p, "seed_a": self.labels[i], "seed_b": self.labels[j],
                                    "n_a": size_i, "n_b": size_j, "intersection": inter,
                                    "inter_over_a": inter / size_i if size_i else None,
                                    "union": int((m[:, i] | m[:, j]).sum()),
                                    "n_scored": n})
            if overlap:
                pd.DataFrame(overlap).to_csv(self.scores_dir / "overlap_by_pct.csv", index=False)
                print(pd.DataFrame(overlap).to_string(index=False))
            st.params = {"selected_pct": pct, "selection": how, "target_union": a.target_union,
                         "n_candidate": len(cand_ids), "n_scored": n, "n_union": int(union.sum()),
                         "n_per_seed": {l: int(masks[:, k].sum()) for k, l in enumerate(self.labels)},
                         "report_pcts": self.report_pcts}
            st.outputs = {"candidate_scores": lineage.file_info(all_path, hash_content=False),
                          "union_top": lineage.file_info(self.union_csv, rows=int(union.sum())),
                          **({"overlap_by_pct": lineage.file_info(self.scores_dir / "overlap_by_pct.csv")} if overlap else {})}
        (self.run_dir / "run.json").write_text(json.dumps({
            "group": self.seed, "run_id": self.run_id, "seeds": [vars(s) for s in self.seeds], "pool_id": self.pool_id,
            "ae_version": self.ae_version, "autoencoder": self.ae_info,
            "classifier_config": str(self.model_dir / "config.json"), "candidate_periods": self.periods,
            "period_overlap_with_pool": self.overlap, "selected_pct": pct, "n_union": int(union.sum()),
            "lineage": lineage.lineage_path(self.run_dir), "finished_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[DONE] {self.union_csv}")

    # 5
    def stage_publish(self, table: str) -> None:
        """union_top.csv를 S3(prod/lookalike/delivery/...)에 올리고 SCRATCH_DB에 그 위의 외부 테이블을 만든다.
        이미 같은 이름의 테이블이 있으면 덮어쓰지 않고 중단한다(DROP은 사람이 결정)."""
        aq.check_table_name(table)
        if not self.union_csv.exists():
            raise FileNotFoundError(f"{self.union_csv}가 없습니다 — score 단계까지 먼저 실행하세요")
        self.aws = self.aws or Aws()
        with open(self.union_csv, encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        columns = [(c, "string" if c == ID_COL else "int" if c.startswith("in_") else "double") for c in header]
        s3_prefix = Layout.s3_uri(f"delivery/{self.seed}/{self.run_id}/{table}")
        print(f"[STEP 5] 테이블 생성: {SCRATCH_DB}.{table} <- {s3_prefix}")
        with lineage.Stage(self.run_dir, "publish_table") as st:
            exists_sql = ("SELECT count(*) AS n FROM information_schema.tables "
                          f"WHERE table_schema = '{SCRATCH_DB}' AND table_name = '{table}'")
            qid, _ = self.aws.run_query(exists_sql, label="table-exists")
            if int(self.aws.query_rows(qid)[0]["n"]) > 0:
                raise SystemExit(f"[중단] {SCRATCH_DB}.{table}이 이미 있습니다 — 덮어쓰지 않습니다(다른 이름을 쓰거나 직접 DROP)")
            stray = [k for k in self.aws.list_keys(s3_prefix)
                     if not k.endswith("/") and not k.endswith("/union_top.csv")]   # union_top.csv는 재시도 시 덮어쓴다
            if stray:
                raise SystemExit(f"[중단] {s3_prefix}에 파일이 이미 있습니다({stray[:2]})")
            n_rows = lineage.count_rows(self.union_csv)
            st.inputs = {"union_top": lineage.file_info(self.union_csv, rows=n_rows),
                         "lineage_of_union": lineage.lineage_path(self.run_dir)}
            self.aws.upload_file(self.union_csv, s3_prefix + "union_top.csv")
            ddl = aq.render_delivery_table_ddl(table, s3_prefix, columns)
            qid, stats = self.aws.run_query(ddl, label="create-delivery-table")
            st.athena.append(lineage.athena_info(qid, stats, lineage.save_sql(self.run_dir, f"publish_{table}", ddl),
                                                 s3_prefix, "create external table"))
            qid, _ = self.aws.run_query(f'SELECT count(*) AS n FROM "{SCRATCH_DB}"."{table}"', label="verify-count")
            n_table = int(self.aws.query_rows(qid)[0]["n"])
            st.params = {"table": f"{SCRATCH_DB}.{table}", "columns": columns}
            st.outputs = {"table": f"{SCRATCH_DB}.{table}", "s3_location": s3_prefix + "union_top.csv",
                          "rows_in_file": n_rows, "rows_in_table": n_table}
            if n_table != n_rows:
                raise RuntimeError(f"행 수 불일치: 파일 {n_rows:,} vs 테이블 {n_table:,}")
        print(f"[OK] {SCRATCH_DB}.{table} 생성 ({n_table:,}행, 열: {[c for c, _ in columns]})")


STAGES = ["seed", "candidate", "encode", "train", "score"]


def main():
    ap = argparse.ArgumentParser(description="Athena seed 테이블(여러 개) + 멀티라벨 분류기 -> 합집합 top N%")
    ap.add_argument("--group", required=True, help="이 묶음 이름(경로: data/seeds/<group>/<run_id>/)")
    ap.add_argument("--seed", action="append", required=True, metavar="라벨=DB.테이블:컬럼",
                    help="Athena seed 테이블(반복 가능). 예: sepo_17177=dev-ptbwa-da.sepo_17177:adid")
    ap.add_argument("--period", action="append", required=True, metavar="YYYY-MM-01:YYYY-MM-DD", help="candidate 기간(반복 가능)")
    ap.add_argument("--ae-version", default=AE_VERSION_LEGACY)
    ap.add_argument("--pool-id")
    ap.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--output-table", metavar="TABLE",
                    help="마지막에 union_top.csv를 올려 dev-ptbwa-da.<TABLE> 외부 테이블 생성(이미 있으면 중단)")
    ap.add_argument("--publish-only", action="store_true",
                    help="추출 단계는 건너뛰고 기존 union_top.csv로 --output-table만 만든다")
    ap.add_argument("--id-mode", help="id_space 자동 판정 덮어쓰기: direct | crosswalk:uuid | crosswalk:platform_ad_id")
    s = ap.add_argument_group("선택")
    s.add_argument("--target-union", type=int, help="합집합 목표 인원(공통 상위 pct를 이분 탐색)")
    s.add_argument("--top-pct", type=float, default=10.0, help="--target-union이 없을 때 seed별 상위 pct")
    s.add_argument("--report-pcts", default="2,4,6,8,10", help="seed 간 교집합을 보고할 상위 pct 목록(쉼표)")
    c = ap.add_argument_group("분류기 학습")
    c.add_argument("--epochs", type=int, default=scoring_config.NUM_EPOCHS)
    c.add_argument("--batch-size", type=int, default=scoring_config.BATCH_SIZE)
    c.add_argument("--lr", type=float, default=scoring_config.LEARNING_RATE)
    c.add_argument("--val-split", type=float, default=scoring_config.VAL_SPLIT)
    c.add_argument("--patience", type=int, default=5)
    c.add_argument("--weight-decay", type=float, default=0.0)
    c.add_argument("--train-seed", type=int, default=42)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--stop-after", choices=STAGES)
    ap.add_argument("--allow-overlap", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    args.imbalance = "posweight"   # 멀티라벨은 라벨별 pos_weight 고정(부모 필드 호환)

    run = MultiRun(args, [SeedTable.parse(x) for x in args.seed])
    run.status()
    if args.dry_run:
        return
    if args.publish_only:
        if not args.output_table:
            raise SystemExit("--publish-only는 --output-table이 필요합니다")
        run.stage_publish(args.output_table)
        return
    run.bind_ae()
    t0 = time.time()
    steps = {"seed": run.stage_seed, "candidate": run.stage_candidate, "encode": run.stage_encode,
             "train": run.stage_train, "score": run.stage_score}
    for name in STAGES:
        steps[name]()
        if args.stop_after == name:
            break
    else:
        if args.output_table:
            run.stage_publish(args.output_table)
    print(f"[END] {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
