# lookalike/pipeline/encode.py
#
# segment CSV -> 임베딩(z_0..z_31) 인코딩 헬퍼. 재학습 없이 학습된 BERT lookup + Autoencoder를
# forward로만 쓴다(embedding/segment_features/config.ARTIFACT_DIR의 model.pt).

from pathlib import Path

import pandas as pd

from embedding.segment_features import build_features_incremental
from embedding.segment_features import config as feat_config
from inference import append_embeddings
from inference import segment_features as infer_segment_features
from scoring import config as scoring_config

ID_COL = scoring_config.ID_COL


def encode_and_append(csv_path: Path, tag: str, dst: Path) -> int:
    """csv_path(segment CSV)에서 dst에 아직 없는 device_ifa만 골라 인코딩해 dst에 append한다.
    전원 이미 인코딩돼 있으면 인코딩 자체를 건너뛴다(후보가 수백만 행이라 재실행 비용이 크다).
    반환값: 새로 추가된 인원 수."""
    dst = Path(dst)
    existing_ids = (
        set(pd.read_csv(dst, usecols=[ID_COL], dtype=str)[ID_COL]) if dst.exists() else set()
    )

    npz_path = build_features_incremental.build_npz(csv_path, tag, skip_ids=existing_ids)
    if npz_path is None:
        print(f"[INFO] {Path(csv_path).name}: 전원 이미 인코딩됨({len(existing_ids)}명 중), 스킵")
        return 0

    tmp_csv = feat_config.ARTIFACT_DIR / f"segment_embeddings_{tag}_new.csv"
    infer_segment_features.run(input_path=str(npz_path), output_path=str(tmp_csv))
    return append_embeddings.append_dedup(tmp_csv, dst)


def encode_to(csv_path: Path, tag: str, dst: Path) -> int:
    """encode_and_append를 부르고, 만들어진 중간 파일(npz/임시 CSV — 후보는 수 GB)을 지운다."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        return encode_and_append(csv_path, tag=tag, dst=dst)
    finally:
        for leftover in (
            feat_config.ARTIFACT_DIR / f"segment_features_{tag}.npz",
            feat_config.ARTIFACT_DIR / f"segment_embeddings_{tag}_new.csv",
        ):
            leftover.unlink(missing_ok=True)


def read_embeddings_for_ids(csv_path: Path, ids: set, chunksize: int = 500_000) -> pd.DataFrame:
    """큰 임베딩 CSV에서 ids에 속한 행만 청크로 읽는다(device_ifa 중복은 첫 값 유지)."""
    cols = [ID_COL, *scoring_config.SEGMENT_EMBED_COLS]
    frames = []
    for chunk in pd.read_csv(csv_path, usecols=cols, dtype={ID_COL: str}, chunksize=chunksize):
        hit = chunk[chunk[ID_COL].isin(ids)]
        if len(hit):
            frames.append(hit)
    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=[ID_COL], keep="first")
