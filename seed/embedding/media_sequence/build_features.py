# seed/embedding/media_sequence/build_features.py
#
# seed_media.csv/pool_media.csv(이벤트 그레인, 합쳐서 최대 14GB) -> device_ifa별
# SASRec 학습/추론용 인코딩 시퀀스(media_features.npz).
# segment_features와 같은 이유로(무거운 전처리를 학습 루프에서 분리) build_features.py를
# 따로 뒀지만, media는 세그먼트와 달리 "유저 1행"이 아니라 이벤트 그레인(유저당 수십~수백
# 행)이라 전체를 pandas로 한 번에 읽으면 메모리가 감당 안 된다 — 그래서 2-pass 스트리밍으로
# 처리한다.
#
#   pass 1 (fit_vocabs): media/inventory_type/ad_type/connection_type 4개 컬럼만 청크
#     단위로 읽어 Counter를 누적하고, 끝에서 한 번에 vocab을 확정한다(원본 문자열 값을
#     메모리에 쌓지 않음).
#   pass 2 (build): 파일을 seed -> pool -> candidate 순서로 처리한다. 각 파일 안에서는
#     device_ifa별로 (ts, media_id, inventory_id, ad_id, connection_id) 튜플을 모았다가
#     (이미 vocab id로 인코딩된 상태라 원본 문자열보다 훨씬 작다) 그 파일 처리가 끝나면
#     시간순 정렬 후 최근 (MAX_SEQ_LEN+1)개만 남겨 확정한다. 이미 앞선 파일에서 확정된
#     device_ifa는 건너뛴다 — pool(4~5월)과 candidate(6월) 양쪽에 걸쳐 활동한 디바이스가
#     실제로 존재해서(세그먼트 파이프라인에서 33,266명 확인, scoring/dataset.py 참고)
#     같은 정책(첫 번째 값 유지)으로 중복을 막는다.
#
# 저장: media_features.npz의 device_ifa/media_ids/inventory_type_ids/ad_type_ids/
#   connection_type_ids는 전부 디바이스별 "가변 길이"(최대 MAX_SEQ_LEN+1)라 dtype=object
#   배열로 저장한다 — dataset.py가 각 디바이스 실제 길이만큼만 잘라 next-item 쌍을 만들어야
#   해서(길이가 제각각), 고정폭으로 미리 패딩해두면 오히려 그 작업을 다시 풀어야 한다.
#
# 2026-08-03 추가: time_of_day_ids(3시간 단위 절대 시간대, config.TIME_OF_DAY_VOCAB_SIZE)/
#   time_gap_ids(TiSASRec 스타일 직전 이벤트와의 간격 버킷, config.TIME_GAP_VOCAB_SIZE)도
#   같은 방식(디바이스별 가변 길이)으로 함께 저장한다 — model.py가 position_embedding을
#   time_gap 기반으로 재정의하고 time_of_day를 새 side feature로 쓴다.
#
# 실행(seed/ 안에서 cd 후): ..\.venv\Scripts\python.exe -m embedding.media_sequence.build_features

import argparse
import os
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from ..common.vocab import CategoryVocab, NA_TOKEN
from . import config

USE_COLS = [
    config.ID_COL,
    config.MEDIA_COL,
    config.INVENTORY_TYPE_COL,
    config.AD_TYPE_COL,
    config.CONNECTION_TYPE_COL,
    config.TS_COL,
]

STORE_LEN = config.MAX_SEQ_LEN + 1  # 학습 시 next-item shift(input/target)에 1개 더 필요

NS_PER_SEC = 1_000_000_000
SEC_PER_DAY = 86400


def _time_of_day_ids(ts_ns: np.ndarray) -> np.ndarray:
    """ts(나노초, SQL에서 이미 Asia/Seoul 로컬시간으로 변환됨) -> 3시간 단위 시간대 버킷.
    0=pad(여기선 안 나옴), 1~8=00-03시.. 21-24시 구간(config.TIME_OF_DAY_VOCAB_SIZE 참고)."""
    seconds_of_day = (ts_ns // NS_PER_SEC) % SEC_PER_DAY
    hour = seconds_of_day // 3600
    return (1 + hour // config.TIME_OF_DAY_BUCKET_HOURS).astype(np.int64)


def _time_gap_id(delta_sec: float) -> int:
    """직전 이벤트와의 간격(초) -> TiSASRec 스타일 버킷. 0=pad, 1=첫 이벤트(위에서 별도
    처리), 2..(2+len(경계))=간격 구간(config.TIME_GAP_BOUNDARIES_SEC 참고)."""
    idx = int(np.searchsorted(config.TIME_GAP_BOUNDARIES_SEC, delta_sec, side="right"))
    return 2 + idx


def _source_paths():
    # config.DATA_FILES 순서(seed -> pool) 그대로 처리한다 — candidate_media.csv는
    # 일부러 여기 안 넣는다(config.py DATA_FILES 주석 참고, --reuse-vocab --input으로
    # 별도 처리).
    paths = [str(config.DATA_DIR / f) for f in config.DATA_FILES]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(f"다음 CSV가 {config.DATA_DIR}에 없습니다: {missing}")
    return paths


def fit_vocabs(paths):
    counters = {col: Counter() for col in (config.MEDIA_COL, config.INVENTORY_TYPE_COL,
                                            config.AD_TYPE_COL, config.CONNECTION_TYPE_COL)}
    for path in paths:
        print(f"[INFO] vocab 적합(1-pass): {path}")
        n_rows = 0
        for chunk in pd.read_csv(path, usecols=USE_COLS, dtype=str, chunksize=config.CHUNK_SIZE):
            for col, counter in counters.items():
                counter.update(CategoryVocab._normalize(v) for v in chunk[col])
            n_rows += len(chunk)
        print(f"[INFO]   {n_rows:,}행 처리")

    media_vocab = CategoryVocab.build_from_counter(
        counters[config.MEDIA_COL], config.MIN_FREQ, config.MAX_VOCAB_SIZE
    )
    inventory_vocab = CategoryVocab.build_from_counter(
        counters[config.INVENTORY_TYPE_COL], config.SIDE_FEATURE_MIN_FREQ, config.INVENTORY_TYPE_MAX_VOCAB_SIZE
    )
    ad_type_vocab = CategoryVocab.build_from_counter(
        counters[config.AD_TYPE_COL], config.SIDE_FEATURE_MIN_FREQ, config.AD_TYPE_MAX_VOCAB_SIZE
    )
    connection_type_vocab = CategoryVocab.build_from_counter(
        counters[config.CONNECTION_TYPE_COL], config.SIDE_FEATURE_MIN_FREQ, config.CONNECTION_TYPE_MAX_VOCAB_SIZE
    )
    print(
        f"[INFO] vocab size: media={len(media_vocab)} inventory_type={len(inventory_vocab)} "
        f"ad_type={len(ad_type_vocab)} connection_type={len(connection_type_vocab)}"
    )
    return media_vocab, inventory_vocab, ad_type_vocab, connection_type_vocab


def build(paths, media_vocab, inventory_vocab, ad_type_vocab, connection_type_vocab):
    ids = []
    media_seqs, inventory_seqs, ad_seqs, connection_seqs = [], [], [], []
    time_of_day_seqs, time_gap_seqs = [], []
    seen = set()

    for path in paths:
        print(f"[INFO] 시퀀스 구성(2-pass): {path}")
        # device_ifa -> [(ts_ns, media_id, inventory_id, ad_id, connection_id, time_of_day_id), ...]
        # 값들은 이미 vocab id(int)로 인코딩해서 담는다 — 원본 문자열을 그대로 쌓으면
        # 이 버킷 하나가 파일 크기(최대 7GB)에 육박할 수 있어 메모리 위험이 크다.
        buckets = defaultdict(list)
        n_rows = 0
        for chunk in pd.read_csv(path, usecols=USE_COLS, dtype=str, chunksize=config.CHUNK_SIZE):
            chunk = chunk.dropna(subset=[config.MEDIA_COL])
            if chunk.empty:
                continue
            n_rows += len(chunk)
            # pandas 버전에 따라 to_datetime의 기본 해상도가 us/ns로 갈릴 수 있어(실측:
            # pandas 3.0.3에서 datetime64[us] 기본) astype("int64")만 하면 실제로는
            # 마이크로초 값이 나와 아래 시간대/간격 버킷 계산이 1000배 어긋난다 —
            # datetime64[ns]로 강제 캐스팅해 항상 진짜 나노초 단위를 보장한다.
            ts_ns = (
                pd.to_datetime(chunk[config.TS_COL], errors="coerce")
                .astype("datetime64[ns]")
                .astype("int64")
                .to_numpy()
            )
            media_ids = chunk[config.MEDIA_COL].map(media_vocab.encode).to_numpy()
            inv_ids = chunk[config.INVENTORY_TYPE_COL].map(inventory_vocab.encode).to_numpy()
            ad_ids = chunk[config.AD_TYPE_COL].map(ad_type_vocab.encode).to_numpy()
            conn_ids = chunk[config.CONNECTION_TYPE_COL].map(connection_type_vocab.encode).to_numpy()
            tod_ids = _time_of_day_ids(ts_ns)
            device_ifas = chunk[config.ID_COL].to_numpy()

            for device_ifa, t, m, inv, ad, conn, tod in zip(
                device_ifas, ts_ns, media_ids, inv_ids, ad_ids, conn_ids, tod_ids
            ):
                if device_ifa in seen:
                    continue
                buckets[device_ifa].append((t, m, inv, ad, conn, tod))
        print(f"[INFO]   {n_rows:,}행 스캔, {len(buckets):,}개 신규 디바이스 후보")

        n_finalized = 0
        for device_ifa, events in buckets.items():
            events.sort(key=lambda e: e[0])

            # 시간 간격 버킷(TiSASRec 스타일)은 STORE_LEN으로 자르기 전, 전체 정렬된
            # 시퀀스 기준으로 계산한다 — 자른 뒤 계산하면 잘림 경계의 첫 이벤트가 실제로는
            # 직전 이벤트가 있는데도 "첫 이벤트"로 잘못 표시된다.
            gap_ids_full = []
            prev_t = None
            for e in events:
                if prev_t is None:
                    gap_ids_full.append(1)  # 첫 이벤트(직전 이벤트 없음)
                else:
                    gap_ids_full.append(_time_gap_id((e[0] - prev_t) / NS_PER_SEC))
                prev_t = e[0]

            events = events[-STORE_LEN:]
            gap_ids_full = gap_ids_full[-STORE_LEN:]

            ids.append(str(device_ifa))
            media_seqs.append(np.array([e[1] for e in events], dtype=np.int16))
            inventory_seqs.append(np.array([e[2] for e in events], dtype=np.int8))
            ad_seqs.append(np.array([e[3] for e in events], dtype=np.int8))
            connection_seqs.append(np.array([e[4] for e in events], dtype=np.int8))
            time_of_day_seqs.append(np.array([e[5] for e in events], dtype=np.int8))
            time_gap_seqs.append(np.array(gap_ids_full, dtype=np.int8))
            seen.add(device_ifa)
            n_finalized += 1
        print(f"[INFO]   {n_finalized:,}개 디바이스 확정 (누적 {len(seen):,})")
        del buckets

    return {
        config.ID_COL: np.array(ids, dtype=object),
        "media_ids": np.array(media_seqs, dtype=object),
        "inventory_type_ids": np.array(inventory_seqs, dtype=object),
        "ad_type_ids": np.array(ad_seqs, dtype=object),
        "connection_type_ids": np.array(connection_seqs, dtype=object),
        "time_of_day_ids": np.array(time_of_day_seqs, dtype=object),
        "time_gap_ids": np.array(time_gap_seqs, dtype=object),
    }


def main():
    parser = argparse.ArgumentParser(
        description="media CSV -> device_ifa별 인코딩 시퀀스(media_features.npz). "
        "기본값(인자 없음)은 config.DATA_FILES(seed_media.csv, pool_media.csv)를 스캔해 "
        "vocab을 새로 적합한다(최초 학습용)."
    )
    parser.add_argument(
        "--input", nargs="+",
        help="처리할 특정 CSV 경로(들). 생략 시 DATA_DIR/config.DATA_FILES를 스캔",
    )
    parser.add_argument(
        "--output", help=f"결과 npz 저장 경로 (생략 시 기본값: {config.FEATURES_NPZ_PATH})",
    )
    parser.add_argument(
        "--reuse-vocab", action="store_true",
        help="이미 학습에 쓴 vocab(vocab_media.json 등)을 그대로 불러와 재사용하고 새로 적합하지 "
        "않는다 — 학습된 모델과 item 인덱스가 어긋나면 안 되는 '추론 전용 증분 처리'(예: 새 "
        "candidate 집단 추가)에 쓴다. 지정하면 vocab 파일도 덮어쓰지 않는다.",
    )
    args = parser.parse_args()

    paths = args.input or _source_paths()
    print(f"[INFO] 대상 파일: {paths}")

    if args.reuse_vocab:
        media_vocab = CategoryVocab.load(config.MEDIA_VOCAB_PATH)
        inventory_vocab = CategoryVocab.load(config.INVENTORY_TYPE_VOCAB_PATH)
        ad_type_vocab = CategoryVocab.load(config.AD_TYPE_VOCAB_PATH)
        connection_type_vocab = CategoryVocab.load(config.CONNECTION_TYPE_VOCAB_PATH)
        print("[INFO] 기존 vocab 재사용(적합 생략)")
    else:
        media_vocab, inventory_vocab, ad_type_vocab, connection_type_vocab = fit_vocabs(paths)

    features = build(paths, media_vocab, inventory_vocab, ad_type_vocab, connection_type_vocab)

    output_path = args.output or config.FEATURES_NPZ_PATH
    os.makedirs(os.path.dirname(str(output_path)) or ".", exist_ok=True)
    if not args.reuse_vocab:
        config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        media_vocab.save(config.MEDIA_VOCAB_PATH)
        inventory_vocab.save(config.INVENTORY_TYPE_VOCAB_PATH)
        ad_type_vocab.save(config.AD_TYPE_VOCAB_PATH)
        connection_type_vocab.save(config.CONNECTION_TYPE_VOCAB_PATH)
    np.savez(output_path, **features)
    print(f"[INFO] {len(features[config.ID_COL]):,}개 디바이스 -> {output_path}")


if __name__ == "__main__":
    main()
