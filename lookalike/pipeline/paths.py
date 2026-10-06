# lookalike/pipeline/paths.py
#
# Athena 접근이 가능한 파이프라인(시나리오 1: 신규 seed, 시나리오 2: 오토인코더 재학습)의
# 로컬/S3 경로 규칙. 로컬 data/ 아래 구조와 s3://ptbwa-dw/prod/lookalike/ 아래 구조를
# 이름까지 1:1로 맞춘다 — 동기화는 같은 상대 경로끼리 하면 된다.
#
#   autoencoders/<ae_version>/        model.pt, vocab, lookup, config.json(pool_id 기록)
#   pools/<pool_id>/                  pool_spec.json, pool_segment.csv
#   candidates/<period_key>/          segment.csv, emb_<ae_version>.csv  (기간별 캐시, seed 제외는 로컬)
#   seeds/<seed>/input/               원본 seed CSV 투입 위치
#   seeds/<seed>/<run_id>/            id_space_check.json, seed_segment.csv, model/, scores/

import re
from datetime import date
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_ROOT = PROJECT_ROOT / "data"

S3_BUCKET = "ptbwa-dw"
S3_ROOT_PREFIX = "prod/lookalike"

# 쿼리 읽기/임시 외부 테이블용 DB. 임시 테이블은 TEMP_TABLE_PREFIX로 시작해야 하고
# (config/iam/lookalike_pipeline_policy.json이 이 접두사에만 CREATE/DELETE 허용), 끝나면 DROP한다.
SCRATCH_DB = "dev-ptbwa-da"
SOURCE_DB = "prod-ptbwa-dw"
TEMP_TABLE_PREFIX = "_tmp_lookalike_"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def _check_name(label: str, value: str) -> str:
    # 경로 조각으로 쓰는 값이라 구분자/상대경로 문자를 막는다.
    if not _NAME_RE.match(value):
        raise ValueError(f"{label} 형식이 올바르지 않습니다: {value!r}")
    return value


def period_key(periods: List[Tuple[str, str]]) -> str:
    """[("2026-01-01","2026-03-31"),("2026-06-01","2026-09-30")] -> '2026-01-01_2026-03-31+2026-06-01_2026-09-30'."""
    if not periods:
        raise ValueError("periods가 비어 있습니다")
    return "+".join(f"{_check_name('period', s)}_{_check_name('period', e)}" for s, e in sorted(periods))


class Layout:
    """로컬 경로와 S3 key를 같은 상대 경로로 계산한다."""

    @staticmethod
    def rel_autoencoder(ae_version: str) -> str:
        return f"autoencoders/{_check_name('ae_version', ae_version)}"

    @staticmethod
    def rel_pool(pool_id: str) -> str:
        return f"pools/{_check_name('pool_id', pool_id)}"

    @staticmethod
    def rel_candidates(periods: List[Tuple[str, str]]) -> str:
        return f"candidates/{period_key(periods)}"

    @staticmethod
    def rel_seed_input(seed: str) -> str:
        return f"seeds/{_check_name('seed', seed)}/input"

    @staticmethod
    def rel_seed_run(seed: str, run_id: str) -> str:
        return f"seeds/{_check_name('seed', seed)}/{_check_name('run_id', run_id)}"

    @staticmethod
    def rel_delivery(seed: str, run_id: str, top_pct: int) -> str:
        return f"delivery/{_check_name('seed', seed)}/{_check_name('run_id', run_id)}/top{int(top_pct)}pct"

    # --- 로컬 경로 ---
    @staticmethod
    def local(rel: str) -> Path:
        return LOCAL_ROOT / rel

    # --- S3 ---
    @staticmethod
    def s3_key(rel: str) -> str:
        return f"{S3_ROOT_PREFIX}/{rel}"

    @staticmethod
    def s3_uri(rel: str, trailing_slash: bool = True) -> str:
        uri = f"s3://{S3_BUCKET}/{S3_ROOT_PREFIX}/{rel}"
        return uri + "/" if trailing_slash else uri


# Athena 쿼리 결과(수명주기 7일 규칙을 이 prefix에 건다).
ATHENA_RESULTS_S3 = f"s3://{S3_BUCKET}/{S3_ROOT_PREFIX}/_athena_results/"


def temp_table_name(seed: str, run_id: str) -> str:
    """seed 목록 위에 만드는 임시 외부 테이블 이름(DROP 대상)."""
    name = f"{TEMP_TABLE_PREFIX}{_check_name('seed', seed)}_{_check_name('run_id', run_id)}"
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


# ---------- 오토인코더 버전 ----------

AE_VERSION_LEGACY = "legacy"
LEGACY_AE_DIR = LOCAL_ROOT / "models" / "segment_features"   # 시나리오 2 이전에 학습한 모델


def ae_dir(ae_version: str) -> Path:
    """ae_version의 산출물 디렉터리(model.pt/vocab/lookup/config.json — embedding/segment_features/artifacts.py)."""
    if ae_version == AE_VERSION_LEGACY:
        return LEGACY_AE_DIR
    return Layout.local(Layout.rel_autoencoder(ae_version))


# ---------- 기간 ----------

def parse_periods(raw: List[str]) -> List[Tuple[str, str]]:
    """['2026-06-01:2026-06-30', ...] -> [('2026-06-01','2026-06-30'), ...]"""
    periods = []
    for item in raw:
        start, sep, end = item.partition(":")
        if not sep:
            raise ValueError(f"--period는 YYYY-MM-01:YYYY-MM-DD 형식입니다: {item!r}")
        periods.append((date.fromisoformat(start).isoformat(), date.fromisoformat(end).isoformat()))
    return periods


def periods_overlap(a: List[Tuple[str, str]], b: List[Tuple[str, str]]) -> bool:
    return any(s1 <= e2 and s2 <= e1 for s1, e1 in a for s2, e2 in b)
