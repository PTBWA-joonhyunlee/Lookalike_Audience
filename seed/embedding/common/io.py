import glob
import os
from typing import Optional


def latest_file(pattern: str) -> Optional[str]:
    """glob 패턴에 맞는 파일 중 가장 최신(수정시간 기준) 파일 경로. 없으면 None."""
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)
