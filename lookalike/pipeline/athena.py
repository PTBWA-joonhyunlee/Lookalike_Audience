# lookalike/pipeline/athena.py
#
# Athena/S3 접근 래퍼(boto3). 이 repo에서 처음으로 Athena를 직접 실행하는 경로 — 이전에는
# 사용자가 콘솔에서 SQL을 돌리고 CSV를 data/에 올려줬다(CLAUDE.md "데이터를 얻는 방법").
#
# 자격증명: 환경변수(AWS_ACCESS_KEY_ID 등)가 있으면 그걸 쓰고, 없으면
# config/LAL_accessKeys.csv(헤더: Access key ID, Secret access key — .gitignore 대상)를 읽는다.
# 키 값은 어디에도 출력하지 않는다.

import csv
import gzip
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import boto3
from botocore.config import Config

from .paths import ATHENA_RESULTS_S3, PROJECT_ROOT, SCRATCH_DB

REGION = "ap-northeast-2"
WORKGROUP = "primary"
ACCESS_KEYS_CSV = PROJECT_ROOT / "config" / "LAL_accessKeys.csv"


def make_session() -> boto3.Session:
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        return boto3.Session(region_name=REGION)
    if ACCESS_KEYS_CSV.exists():
        with open(ACCESS_KEYS_CSV, encoding="utf-8-sig", newline="") as f:
            row = {k.strip(): v.strip() for k, v in next(csv.DictReader(f)).items()}
        return boto3.Session(
            aws_access_key_id=row["Access key ID"],
            aws_secret_access_key=row["Secret access key"],
            region_name=REGION,
        )
    return boto3.Session(region_name=REGION)


def split_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"s3:// 경로가 아닙니다: {uri}")
    bucket, _, key = uri[5:].partition("/")
    return bucket, key


class Aws:
    def __init__(self):
        session = make_session()
        cfg = Config(retries={"max_attempts": 8, "mode": "adaptive"}, max_pool_connections=32)
        self.athena = session.client("athena", config=cfg)
        self.s3 = session.client("s3", config=cfg)

    # ---------- Athena ----------

    def run_query(self, sql: str, database: str = SCRATCH_DB, timeout_sec: int = 6 * 3600, label: str = "") -> Tuple[str, dict]:
        """쿼리를 제출하고 끝날 때까지 기다린다. 실패/취소면 사유를 담아 RuntimeError를 낸다.
        반환: (query_execution_id, statistics)."""
        resp = self.athena.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": database, "Catalog": "AwsDataCatalog"},
            WorkGroup=WORKGROUP,
            ResultConfiguration={"OutputLocation": ATHENA_RESULTS_S3},
        )
        qid = resp["QueryExecutionId"]
        tag = f"[athena{(' ' + label) if label else ''} {qid[:8]}]"
        print(f"{tag} 제출")
        start, delay = time.time(), 2.0
        while True:
            ex = self.athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
            state = ex["Status"]["State"]
            if state == "SUCCEEDED":
                stats = ex.get("Statistics", {})
                scanned_gb = stats.get("DataScannedInBytes", 0) / 1e9
                print(f"{tag} 완료 ({time.time() - start:.0f}s, 스캔 {scanned_gb:.1f}GB)")
                return qid, stats
            if state in ("FAILED", "CANCELLED"):
                reason = ex["Status"].get("StateChangeReason", "")
                raise RuntimeError(f"{tag} {state}: {reason}")
            if time.time() - start > timeout_sec:
                self.athena.stop_query_execution(QueryExecutionId=qid)
                raise TimeoutError(f"{tag} {timeout_sec}s 초과로 중지")
            time.sleep(delay)
            delay = min(delay * 1.5, 15.0)

    def skp_snapshot(self) -> dict:
        """추출 시점 skp 최신 파티션(= 세그먼트 스냅샷). lineage 기록용이라 실패해도 실행을 막지 않는다."""
        from .athena_queries import render_skp_snapshot
        try:
            qid, _ = self.run_query(render_skp_snapshot(), label="skp-snapshot")
            return self.query_rows(qid)[0]
        except Exception as e:
            return {"error": str(e)[:200]}

    def query_rows(self, qid: str) -> List[Dict[str, str]]:
        """작은 SELECT 결과(id_space_check 등)를 컬럼명->값 dict 리스트로 읽는다."""
        rows, header = [], None
        for page in self.athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
            for r in page["ResultSet"]["Rows"]:
                vals = [c.get("VarCharValue") for c in r["Data"]]
                if header is None:
                    header = vals
                else:
                    rows.append(dict(zip(header, vals)))
        return rows

    # ---------- S3 ----------

    def upload_file(self, local_path: Path, s3_uri: str) -> None:
        bucket, key = split_s3_uri(s3_uri)
        self.s3.upload_file(str(local_path), bucket, key)

    def list_keys(self, prefix_uri: str) -> List[str]:
        bucket, prefix = split_s3_uri(prefix_uri)
        keys = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            keys.extend(o["Key"] for o in page.get("Contents", []))
        return keys

    def delete_prefix(self, prefix_uri: str) -> int:
        """UNLOAD는 대상 prefix가 비어 있어야 하므로 재실행 전에 비운다."""
        bucket, prefix = split_s3_uri(prefix_uri)
        if not prefix.startswith("prod/lookalike/") or prefix.count("/") < 3:
            raise ValueError(f"안전장치: prod/lookalike/ 아래 하위 경로만 삭제할 수 있습니다: {prefix_uri}")
        keys = self.list_keys(prefix_uri)
        for i in range(0, len(keys), 1000):
            self.s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True},
            )
        return len(keys)

    def download_concat(self, prefix_uri: str, out_path: Path, header: str, workers: int = 8) -> int:
        """prefix 아래 UNLOAD 결과 파트(.gz 또는 평문)를 전부 내려받아 header 한 줄 + 본문으로
        하나의 CSV로 합친다. 반환: 데이터 행 수."""
        bucket, _ = split_s3_uri(prefix_uri)
        keys = [k for k in self.list_keys(prefix_uri) if not k.endswith("/")]
        if not keys:
            raise RuntimeError(f"{prefix_uri} 아래에 결과 파일이 없습니다(쿼리 결과가 0행일 수 있음)")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        parts_dir = out_path.parent / f"_parts_{out_path.stem}"
        parts_dir.mkdir(exist_ok=True)
        try:
            def fetch(i_key):
                i, key = i_key
                dst = parts_dir / f"{i:06d}{'.gz' if key.endswith('.gz') else ''}"
                self.s3.download_file(bucket, key, str(dst))
                return dst

            print(f"[s3] {len(keys)}개 파트 다운로드: {prefix_uri}")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                parts = list(ex.map(fetch, enumerate(keys)))

            n_lines = 0
            with open(out_path, "wb") as out:
                out.write(header.encode("utf-8") + b"\n")
                for p in sorted(parts):
                    opener = gzip.open if p.suffix == ".gz" else open
                    with opener(p, "rb") as src:
                        while chunk := src.read(1 << 22):
                            out.write(chunk)
                            n_lines += chunk.count(b"\n")
            return n_lines
        finally:
            shutil.rmtree(parts_dir, ignore_errors=True)
