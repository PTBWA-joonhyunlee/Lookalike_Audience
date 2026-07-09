# pipeline/config.py
#
# run_all.py의 --config가 가리키는 JSON 설정 파일을 읽는다.
# 스키마는 config/pipeline.example.json 참고.

from pathlib import Path
from typing import Any, Dict, Union

from embedding.common.config_file import load_json_config

KNOWN_KEYS = {"device", "raw", "models", "embeddings", "train", "stratify", "scoring_output", "backtest"}


def load_pipeline_config(path: Union[str, Path]) -> Dict[str, Any]:
    return load_json_config(path, KNOWN_KEYS)
