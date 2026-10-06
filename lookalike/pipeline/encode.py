# lookalike/pipeline/encode.py
#
# segment CSV -> 임베딩(z_0..z_31) 인코딩 헬퍼. 재학습 없이 학습된 BERT lookup + Autoencoder를
# forward로만 쓴다. 어떤 오토인코더를 쓸지는 ae_dir(= data/autoencoders/<ae_version>/, legacy는
# embedding/segment_features/config.ARTIFACT_DIR)로 정한다 — 구조는 embedding/segment_features/artifacts.py 참고.

from pathlib import Path

import pandas as pd

from embedding.segment_features import build_features_incremental
from embedding.segment_features import config as feat_config
from inference import segment_features as infer_segment_features
from scoring import config as scoring_config

ID_COL = scoring_config.ID_COL


def encode_and_append(csv_path: Path, tag: str, dst: Path, ae_dir: Path = None, chunk_rows: int = 500_000) -> int:
    """csv_path(segment CSV)에서 dst에 아직 없는 device_ifa만 골라 chunk_rows행씩 인코딩해 dst에 append한다.
    청크 단위라 수백만 행도 메모리가 일정하고, 중간에 죽어도 다시 실행하면 이미 쓴 행은 건너뛴다.
    반환값: 새로 추가된 인원 수."""
    dst = Path(dst)
    ae_dir = Path(ae_dir) if ae_dir else feat_config.ARTIFACT_DIR
    existing_ids = (
        set(pd.read_csv(dst, usecols=[ID_COL], dtype=str)[ID_COL]) if dst.exists() else set()
    )
    n_before = len(existing_ids)

    total = 0
    for i, df in enumerate(pd.read_csv(csv_path, dtype=str, chunksize=chunk_rows)):
        df = df[~df[ID_COL].isin(existing_ids)].drop_duplicates(subset=[ID_COL])
        if df.empty:
            continue
        npz_path = build_features_incremental.build_npz_from_df(df.reset_index(drop=True), f"{tag}_{i:04d}", ae_dir=ae_dir)
        tmp_csv = ae_dir / f"segment_embeddings_{tag}_{i:04d}_new.csv"
        try:
            infer_segment_features.run(input_path=str(npz_path), model_dir=str(ae_dir), output_path=str(tmp_csv))
            write_header = not dst.exists()
            with open(dst, "a", encoding="utf-8", newline="") as out:
                pd.read_csv(tmp_csv, dtype={ID_COL: str}).to_csv(out, header=write_header, index=False)
        finally:
            Path(npz_path).unlink(missing_ok=True)
            tmp_csv.unlink(missing_ok=True)
        existing_ids.update(df[ID_COL])
        total += len(df)
        print(f"[INFO] {Path(csv_path).name}: 청크 {i} 완료 — 누적 신규 {total:,}명")
    if total == 0:
        print(f"[INFO] {Path(csv_path).name}: 전원 이미 인코딩됨({n_before}명 중), 스킵")
    return total


def encode_to(csv_path: Path, tag: str, dst: Path, ae_dir: Path = None) -> int:
    """encode_and_append + 중단 시 남은 중간 파일(npz/임시 CSV) 정리."""
    dst = Path(dst)
    ae_dir = Path(ae_dir) if ae_dir else feat_config.ARTIFACT_DIR
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        return encode_and_append(csv_path, tag=tag, dst=dst, ae_dir=ae_dir)
    finally:
        for pattern in (f"segment_features_{tag}_*.npz", f"segment_embeddings_{tag}_*_new.csv"):
            for leftover in ae_dir.glob(pattern):
                leftover.unlink(missing_ok=True)


def read_embeddings_for_ids(csv_path: Path, ids: set, chunksize: int = 500_000) -> pd.DataFrame:
    """큰 임베딩 CSV에서 ids에 속한 행만 청크로 읽는다(device_ifa 중복은 첫 값 유지)."""
    cols = [ID_COL, *scoring_config.SEGMENT_EMBED_COLS]
    frames = []
    dtypes = {ID_COL: str, **{c: "float32" for c in scoring_config.SEGMENT_EMBED_COLS}}
    for chunk in pd.read_csv(csv_path, usecols=cols, dtype=dtypes, chunksize=chunksize):
        hit = chunk[chunk[ID_COL].isin(ids)]
        if len(hit):
            frames.append(hit)
    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=[ID_COL], keep="first")
