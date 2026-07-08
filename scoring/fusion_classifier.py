# scoring/fusion_classifier.py
#
# FusionClassifier 모델 정의 + 아티팩트 저장/로드. train_supervised_lookalike.py(학습)와
# infer_supervised_lookalike.py(스코어링)가 공유하는 자원 — embedding/user_profile/model.py를
# train/inference가 공유하는 것과 같은 구조.

import json
import os
from typing import Union

import torch
import torch.nn as nn

META_FILENAME = "meta.json"
MODEL_FILENAME = "model.pt"


class FusionClassifier(nn.Module):
    def __init__(self, in_dim: int, hidden_dim: int = 64, dropout: float = 0.2):
        super().__init__()
        self.in_dim = in_dim
        self.hidden_dim = hidden_dim
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def save_artifacts(model: FusionClassifier, model_dir: Union[str, os.PathLike]) -> None:
    os.makedirs(model_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(str(model_dir), MODEL_FILENAME))
    meta = {"in_dim": model.in_dim, "hidden_dim": model.hidden_dim}
    with open(os.path.join(str(model_dir), META_FILENAME), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f"[INFO] 분류기 저장: {model_dir}")


def load_artifacts(model_dir: Union[str, os.PathLike]) -> FusionClassifier:
    with open(os.path.join(str(model_dir), META_FILENAME), "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    model = FusionClassifier(in_dim=meta["in_dim"], hidden_dim=meta["hidden_dim"])
    model.load_state_dict(
        torch.load(os.path.join(str(model_dir), MODEL_FILENAME), map_location="cpu")
    )
    model.eval()
    return model
