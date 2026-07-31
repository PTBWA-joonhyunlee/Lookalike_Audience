# seed/scoring/model.py
#
# segment 임베딩(32dim)만 입력으로 받는 얕은 지도학습 분류기 — addi 트랙의 fusion
# 분류기(concat된 임베딩 -> MLP -> sigmoid)와 같은 형태를, profile/media 임베딩이
# 아직 없어 segment 임베딩 하나만으로 축소한 버전. forward()는 logit을 반환하고
# (BCEWithLogitsLoss와 맞춤), 확률이 필요하면 호출부에서 sigmoid를 씌운다.

import torch.nn as nn


class LookalikeClassifier(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, dropout: float = 0.2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)
