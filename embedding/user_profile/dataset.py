# embedding/user_profile/dataset.py

from typing import Dict

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from .numeric import NumericScaler
from ..common.vocab import CategoryVocab


class UserProfileDataset(Dataset):
    def __init__(
        self,
        df: pd.DataFrame,
        cat_field_specs: Dict[str, dict],
        cat_vocabs: Dict[str, CategoryVocab],
        numeric_scalers: Dict[str, NumericScaler],
        id_col: str = "req_user_id",
    ):
        self.ids = df[id_col].astype(str).to_numpy()
        self.cat_fields = list(cat_vocabs.keys())
        self.numeric_fields = list(numeric_scalers.keys())

        self.cat_data = {}
        for field, vocab in cat_vocabs.items():
            series = cat_field_specs[field]["preprocess"](df[field])
            self.cat_data[field] = vocab.encode_series(series)

        numeric_cols, mask_cols = [], []
        for field, scaler in numeric_scalers.items():
            scaled, mask = scaler.transform(df[field])
            numeric_cols.append(scaled)
            mask_cols.append(mask)
        n = len(df)
        self.numeric_data = np.stack(numeric_cols, axis=1) if numeric_cols else np.zeros((n, 0), dtype=np.float32)
        self.numeric_mask = np.stack(mask_cols, axis=1) if mask_cols else np.zeros((n, 0), dtype=np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        cat = {f: torch.tensor(self.cat_data[f][idx], dtype=torch.long) for f in self.cat_fields}
        numeric = torch.tensor(self.numeric_data[idx], dtype=torch.float32)
        numeric_mask = torch.tensor(self.numeric_mask[idx], dtype=torch.float32)
        return str(self.ids[idx]), cat, numeric, numeric_mask
