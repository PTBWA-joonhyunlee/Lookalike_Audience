# lookalike/train/segment_features.py
#
# segment_features Autoencoder 학습(시나리오 2). pool segment CSV로 피처를 만들고, 학습한 모델과
# 그 모델을 쓰는 데 필요한 vocab/lookup/config.json을 ae_dir(= data/autoencoders/<ae_version>/)에
# 한 벌로 저장한다 — embedding/segment_features/artifacts.py 참고. 임베딩 추출은 하지 않는다
# (inference/segment_features.py, pipeline/encode.py).
#
# 재구성 손실의 복원 타깃에는 .detach()를 적용한다(인코더/디코더가 서로를 향해 임의의 상수로
# 붕괴하는 것을 막는다 — embedding/segment_features/model.py 주석 참고).

import copy
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Subset
from tqdm.auto import tqdm

from collections import Counter

from embedding.common.device import resolve_device
from embedding.segment_features import artifacts, config
from embedding.segment_features.bert_lookup import SegmentEmbeddingLookup
from embedding.common.vocab import CategoryVocab
from embedding.segment_features.build_features import _first_id, build
from embedding.segment_features.dataset import SegmentFeaturesDataset
from embedding.segment_features.model import POOLED_GROUPS


@dataclass
class TrainParams:
    num_epochs: int = config.NUM_EPOCHS
    batch_size: int = config.BATCH_SIZE
    learning_rate: float = config.LEARNING_RATE
    val_split: float = 0.05        # 재구성 손실 검증용(에폭 선택에 쓴다)
    patience: int = 5              # val 손실이 이만큼 안 내려가면 중단
    seed: int = 42


def git_commit() -> Optional[str]:
    """현재 HEAD 짧은 해시. 커밋 안 된 변경이 있으면 '+dirty'를 붙인다(재현 가능성 표시)."""
    try:
        cwd = Path(__file__).resolve().parent
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=cwd, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, cwd=cwd, timeout=10).stdout.strip()
        return (head + ("+dirty" if dirty else "")) or None
    except Exception:
        return None


def _count_csv_rows(path: Path, chunk: int = 1 << 22) -> int:
    newline = b"\n"
    n, last = 0, newline
    with open(path, "rb") as f:
        while block := f.read(chunk):
            n += block.count(newline)
            last = block[-1:]
    return max(n + (0 if last == newline else 1) - 1, 0)   # 헤더 제외


def prepare_ae_dir(ae_dir: Path, pool_segment_csv: Path, max_rows: Optional[int] = None, seed: int = 42,
                   chunk_rows: int = 500_000, bert_lookup_from: Path = None):
    """pool segment CSV로 학습용 피처 npz와 age vocab을 만들고 lookup을 ae_dir에 놓는다.
    반환: (npz 경로, 데이터 정보 dict).

    메모리: CSV를 chunk_rows씩 두 번 훑는다(1: age vocab 집계, 2: 피처 인코딩) — 전체를 DataFrame으로
    올리지 않고, 인덱스 배열은 int32로 저장한다(행당 약 0.8KB). max_rows보다 pool이 크면 seed 고정
    무작위(비복원)로 max_rows행만 학습에 쓴다 — 어떤 행을 썼는지 재현 가능하도록 seed를 기록한다.
    lookup은 taxonomy에만 의존하고 데이터와 무관하므로 기본은 legacy 것을 복사한다."""
    ae_dir.mkdir(parents=True, exist_ok=True)
    lookup_path = ae_dir / artifacts.BERT_LOOKUP_FILE
    if not lookup_path.exists():
        src = bert_lookup_from if bert_lookup_from is not None else config.BERT_LOOKUP_PATH
        if Path(src).exists():
            lookup_path.write_bytes(Path(src).read_bytes())
        else:
            SegmentEmbeddingLookup.build().save(lookup_path)
    lookup = SegmentEmbeddingLookup.load(lookup_path)

    n_total = _count_csv_rows(pool_segment_csv)
    keep = None
    if max_rows and n_total > max_rows:
        keep = np.zeros(n_total, dtype=bool)
        keep[np.random.default_rng(seed).choice(n_total, size=max_rows, replace=False)] = True
    n_used = int(keep.sum()) if keep is not None else n_total
    print(f"[INFO] pool segment {n_total:,}행 중 {n_used:,}행으로 학습 피처 생성 "
          f"({'무작위 샘플 seed=%d' % seed if keep is not None else '전체'})")

    def chunks():
        offset = 0
        for df in pd.read_csv(pool_segment_csv, dtype=str, chunksize=chunk_rows):
            part = df[keep[offset:offset + len(df)]] if keep is not None else df
            offset += len(df)
            if len(part):
                yield part.reset_index(drop=True)

    counter = Counter()
    for df in chunks():                                   # pass 1: age vocab
        counter.update(CategoryVocab._normalize(v) for v in df[config.AGE_BRACKET_ID_COL].map(_first_id))
    age_vocab = CategoryVocab.build_from_counter(counter)
    age_vocab.save(ae_dir / artifacts.AGE_VOCAB_FILE)

    parts = {}
    for i, df in enumerate(chunks()):                     # pass 2: 피처
        features, _ = build(df, lookup, age_vocab=age_vocab)
        for k, v in features.items():
            if k.endswith("_idx"):
                v = v.astype(np.int32)
            parts.setdefault(k, []).append(v)
        if i % 5 == 0:
            print(f"[INFO] 피처 청크 {i} 완료")
    merged = {k: np.concatenate(v) for k, v in parts.items()}
    npz_path = ae_dir / "segment_features_pool.npz"
    np.savez(npz_path, **merged)
    print(f"[INFO] {n_used:,}명 -> {npz_path}")
    return npz_path, {"n_pool_total": n_total, "n_rows_used": n_used, "subsampled": keep is not None,
                      "subsample_seed": seed if keep is not None else None, "max_rows": max_rows}


def train_ae(
    ae_dir: Path,
    npz_path: Path,
    params: TrainParams = None,
    spec: artifacts.ModelSpec = None,
    device: str = "auto",
) -> dict:
    """ae_dir에 vocab/lookup이 이미 있어야 한다(prepare_ae_dir). val 재구성 손실이 가장 낮은 에폭의
    가중치를 model.pt로 저장하고, 학습 결과(history 포함)를 dict로 돌려준다."""
    params = params or TrainParams()
    spec = spec or artifacts.ModelSpec()
    device = resolve_device(device)
    torch.manual_seed(params.seed)
    print(f"[INFO] device={device} params={asdict(params)} model={spec.to_dict()}")

    dataset = SegmentFeaturesDataset(npz_path)
    n = len(dataset)
    perm = np.random.default_rng(params.seed).permutation(n)
    n_val = int(n * params.val_split)
    val_idx, train_idx = perm[:n_val], perm[n_val:]
    train_loader = DataLoader(Subset(dataset, train_idx), batch_size=min(params.batch_size, len(train_idx)), shuffle=True)
    val_loader = DataLoader(Subset(dataset, val_idx), batch_size=4096, shuffle=False)

    model = artifacts.build_model(ae_dir, spec).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=params.learning_rate)
    gender_criterion, age_criterion = torch.nn.MSELoss(), torch.nn.CrossEntropyLoss()

    def batch_loss(batch):
        _, gender_pred, age_logits, projections, recons = model(batch)
        loss = gender_criterion(gender_pred, batch["gender_score"]) + age_criterion(age_logits, batch["age_bracket_idx"])
        for g in POOLED_GROUPS:
            loss = loss + torch.nn.functional.mse_loss(recons[g], projections[g].detach())
        return loss

    best = {"val_loss": float("inf"), "epoch": 0, "state": None}
    history, stale = [], 0
    for epoch in range(1, params.num_epochs + 1):
        model.train()
        total = 0.0
        for _, batch in tqdm(train_loader, desc=f"epoch {epoch}/{params.num_epochs}", leave=False, mininterval=5.0):
            batch = {k: v.to(device) for k, v in batch.items()}
            optimizer.zero_grad()
            loss = batch_loss(batch)
            loss.backward()
            optimizer.step()
            total += loss.item() * batch["gender_score"].shape[0]
        train_loss = total / len(train_idx)

        model.eval()
        v_total = 0.0
        with torch.no_grad():
            for _, batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                v_total += batch_loss(batch).item() * batch["gender_score"].shape[0]
        val_loss = v_total / max(len(val_idx), 1)
        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss})
        print(f"[epoch {epoch}/{params.num_epochs}] train_loss={train_loss:.6f} val_loss={val_loss:.6f}")

        if val_loss < best["val_loss"]:
            best.update(val_loss=val_loss, epoch=epoch, state=copy.deepcopy(model.state_dict()))
            stale = 0
        else:
            stale += 1
            if stale >= params.patience:
                print(f"[INFO] early stop: {params.patience} 에폭 동안 val 손실 개선 없음(best epoch {best['epoch']})")
                break

    torch.save(best["state"], ae_dir / artifacts.MODEL_FILE)
    print(f"[INFO] best epoch {best['epoch']} (val_loss={best['val_loss']:.6f}) 모델 저장: {ae_dir / artifacts.MODEL_FILE}")
    return {
        **asdict(params), "device": str(device), "n_train": int(len(train_idx)), "n_val": int(n_val),
        "best_epoch": best["epoch"], "best_val_loss": best["val_loss"], "epochs_run": len(history),
        "history": history, "torch_version": torch.__version__,
    }


def write_config(ae_dir: Path, ae_version: str, spec: artifacts.ModelSpec, train_result: dict, pool_spec: dict,
                 age_vocab_size: int) -> Path:
    cfg = {
        "ae_version": ae_version,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "model": spec.to_dict(),
        "features": {
            "pooled_max_len": config.POOLED_MAX_LEN, "age_vocab_size": age_vocab_size,
            "bert_model": config.BERT_MODEL_NAME, "embed_dim": spec.z_dim,
        },
        "train": train_result,
        "pool": {k: v for k, v in pool_spec.items() if k != "dir"},
        "files": {"model_sha256": artifacts.file_sha256(ae_dir / artifacts.MODEL_FILE)},
    }
    path = ae_dir / artifacts.CONFIG_FILE
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
