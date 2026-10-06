# lookalike/pipeline/lineage.py
#
# 단계별 추적 기록(lineage). "이 결과가 어떤 기간의 어떤 데이터로, 어떤 쿼리/모델/설정을 거쳐 나왔나"를
# 산출물 옆의 lineage.json에 단계 순서대로 남긴다. 각 레코드:
#   stage / status / started_at / finished_at / git_commit
#   params    그 단계에 준 설정(기간, 표본 비율, 학습 하이퍼파라미터 등)
#   inputs    입력 파일(경로, 크기, 행 수, sha256) 또는 입력 데이터 출처(테이블/파티션/스냅샷)
#   models    그 단계에 쓴 모델(ae_version, model.pt 해시 등)
#   athena    실행한 쿼리(query_id, SQL 파일, 스캔량, 결과 S3 경로)
#   outputs   만든 파일(경로, 크기, 행 수, sha256)
# lineage.json은 산출물 소유 디렉터리마다 하나다(pools/<pool_id>/, autoencoders/<ae_version>/,
# candidates/<period_key>/, seeds/<seed>/<run_id>/) — 후보/pool 같은 공유 캐시의 출처가 run마다
# 중복 기록되지 않는다. run의 lineage.json은 그 소유 디렉터리들의 lineage 경로를 가리킨다.
# 쿼리 SQL 원문은 소유 디렉터리의 queries/<name>.sql로 저장한다.

import hashlib
import json
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from .paths import PROJECT_ROOT

LINEAGE_FILE = "lineage.json"


def _rel(path) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(p)


def sha256_16(path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()[:16]


def text_sha256_16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_info(path, rows: Optional[int] = None, hash_content: bool = True) -> dict:
    p = Path(path)
    st = p.stat()
    info = {"path": _rel(p), "size_bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}
    if rows is not None:
        info["rows"] = rows
    if hash_content:
        info["sha256_16"] = sha256_16(p)
    return info


def count_rows(path, header: bool = True, chunk: int = 1 << 22) -> int:
    """텍스트 파일의 데이터 행 수(줄바꿈 기준, 헤더 제외)."""
    n = 0
    last = b"\n"
    with open(path, "rb") as f:
        while block := f.read(chunk):
            n += block.count(b"\n")
            last = block[-1:]
    if last != b"\n":
        n += 1
    return max(n - (1 if header else 0), 0)


def git_state() -> Optional[str]:
    try:
        cwd = Path(__file__).resolve().parent
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=cwd, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, cwd=cwd, timeout=10).stdout.strip()
        return (head + ("+dirty" if dirty else "")) or None
    except Exception:
        return None


def save_sql(owner_dir, name: str, sql: str) -> dict:
    """실행한 SQL 원문을 owner_dir/queries/<name>.sql로 저장하고 {file, sha256_16}을 돌려준다."""
    path = Path(owner_dir) / "queries" / f"{name}.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sql, encoding="utf-8")
    return {"sql_file": _rel(path), "sql_sha256_16": text_sha256_16(sql)}


def athena_info(query_id: str, stats: dict, sql_ref: dict = None, result_s3: str = None, label: str = "") -> dict:
    info = {"query_id": query_id, "workgroup": "primary",
            "data_scanned_bytes": stats.get("DataScannedInBytes"),
            "engine_ms": stats.get("EngineExecutionTimeInMillis"),
            "total_ms": stats.get("TotalExecutionTimeInMillis")}
    if label:
        info["label"] = label
    if sql_ref:
        info.update(sql_ref)
    if result_s3:
        info["result_s3"] = result_s3
    return info


def read(owner_dir) -> list:
    path = Path(owner_dir) / LINEAGE_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def lineage_path(owner_dir) -> str:
    return _rel(Path(owner_dir) / LINEAGE_FILE)


class Stage:
    """with Stage(owner_dir, "pool_segment") as st: st.params[...]=...; st.inputs[...]=...
    블록이 끝나면(예외여도) 레코드를 owner_dir/lineage.json에 추가한다."""

    def __init__(self, owner_dir, stage: str):
        self.owner_dir = Path(owner_dir)
        self.rec = {"stage": stage, "status": "running", "git_commit": git_state(),
                    "started_at": datetime.now().isoformat(timespec="seconds")}
        self.params, self.inputs, self.models, self.athena, self.outputs, self.notes = {}, {}, {}, [], {}, {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.rec["status"] = "failed" if exc_type else "ok"
        if exc_type:
            self.rec["error"] = "".join(traceback.format_exception_only(exc_type, exc)).strip()[:500]
        self.rec["finished_at"] = datetime.now().isoformat(timespec="seconds")
        for key in ("params", "inputs", "models", "athena", "outputs", "notes"):
            value = getattr(self, key)
            if value:
                self.rec[key] = value
        records = read(self.owner_dir)
        records.append(self.rec)
        self.owner_dir.mkdir(parents=True, exist_ok=True)
        (self.owner_dir / LINEAGE_FILE).write_text(
            json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return False
