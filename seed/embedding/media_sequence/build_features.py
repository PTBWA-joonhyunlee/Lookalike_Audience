# seed/embedding/media_sequence/build_features.py
#
# 04b_seed_media.csv/05b_pool_media.csv/07b_candidate_media.csv(이벤트 그레인, 합쳐서
# 최대 14GB) -> device_ifa별 SASRec 학습/추론용 인코딩 시퀀스(media_features.npz).
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
# 실행(seed/ 안에서 cd 후): ..\.venv\Scripts\python.exe -m embedding.media_sequence.build_features

import argparse
import glob as globmod
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


def _source_paths():
    # 파일명 정렬 = 04b(seed) -> 05b(pool) -> 07b(candidate) 순서와 자연스럽게 일치한다.
    paths = sorted(globmod.glob(str(config.DATA_DIR / config.DATA_GLOB)))
    if not paths:
        raise FileNotFoundError(f"{config.DATA_GLOB} 패턴의 CSV가 {config.DATA_DIR}에 없습니다.")
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
    ids, media_seqs, inventory_seqs, ad_seqs, connection_seqs = [], [], [], [], []
    seen = set()

    for path in paths:
        print(f"[INFO] 시퀀스 구성(2-pass): {path}")
        # device_ifa -> [(ts_ns, media_id, inventory_id, ad_id, connection_id), ...]
        # 값들은 이미 vocab id(int)로 인코딩해서 담는다 — 원본 문자열을 그대로 쌓으면
        # 이 버킷 하나가 파일 크기(최대 7GB)에 육박할 수 있어 메모리 위험이 크다.
        buckets = defaultdict(list)
        n_rows = 0
        for chunk in pd.read_csv(path, usecols=USE_COLS, dtype=str, chunksize=config.CHUNK_SIZE):
            chunk = chunk.dropna(subset=[config.MEDIA_COL])
            if chunk.empty:
                continue
            n_rows += len(chunk)
            ts_ns = pd.to_datetime(chunk[config.TS_COL], errors="coerce").astype("int64").to_numpy()
            media_ids = chunk[config.MEDIA_COL].map(media_vocab.encode).to_numpy()
            inv_ids = chunk[config.INVENTORY_TYPE_COL].map(inventory_vocab.encode).to_numpy()
            ad_ids = chunk[config.AD_TYPE_COL].map(ad_type_vocab.encode).to_numpy()
            conn_ids = chunk[config.CONNECTION_TYPE_COL].map(connection_type_vocab.encode).to_numpy()
            device_ifas = chunk[config.ID_COL].to_numpy()

            for device_ifa, t, m, inv, ad, conn in zip(device_ifas, ts_ns, media_ids, inv_ids, ad_ids, conn_ids):
                if device_ifa in seen:
                    continue
                buckets[device_ifa].append((t, m, inv, ad, conn))
        print(f"[INFO]   {n_rows:,}행 스캔, {len(buckets):,}개 신규 디바이스 후보")

        n_finalized = 0
        for device_ifa, events in buckets.items():
            events.sort(key=lambda e: e[0])
            events = events[-STORE_LEN:]

            ids.append(str(device_ifa))
            media_seqs.append(np.array([e[1] for e in events], dtype=np.int16))
            inventory_seqs.append(np.array([e[2] for e in events], dtype=np.int8))
            ad_seqs.append(np.array([e[3] for e in events], dtype=np.int8))
            connection_seqs.append(np.array([e[4] for e in events], dtype=np.int8))
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
    }


def main():
    parser = argparse.ArgumentParser(
        description="media CSV -> device_ifa별 인코딩 시퀀스(media_features.npz). "
        "기본값(인자 없음)은 DATA_GLOB 전체를 스캔해 vocab을 새로 적합한다(최초 학습용)."
    )
    parser.add_argument(
        "--input", nargs="+",
        help="처리할 특정 CSV 경로(들). 생략 시 DATA_DIR/DATA_GLOB 전체를 스캔",
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
