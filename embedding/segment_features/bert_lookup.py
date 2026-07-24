# embedding/segment_features/bert_lookup.py
#
# segment_id -> 사전학습 문장임베딩 lookup 테이블. 거주/제품 관심사/콘텐츠 관심사/기타가
# 전부 이 하나의 lookup을 공유한다(2026-07-24 결정) — 그룹 구분은 pooling 단계에서 한다.
# 최초 실행 시 `pip install sentence-transformers`와 모델 다운로드(네트워크 필요)가 필요하다.
#
# index 0은 padding용으로 예약(전부 0벡터) — embedding/media_sequence의
# genre_embedding(nn.EmbeddingBag, padding_idx=0)과 동일한 컨벤션. build_features.py는
# 디바이스별 pooled 벡터를 직접 저장하지 않고 이 인덱스로만 인코딩하고, 실제 mean pooling은
# 학습 시 nn.EmbeddingBag.from_pretrained(lookup.vectors, padding_idx=0)이 배치 단위로 한다
# — 디바이스 수 x 768dim 벡터를 그룹마다 통째로 저장하면 1% 샘플(53만 명)만으로도 6GB가
# 넘어 전체 모집단(5,300만 명) 규모에서는 저장이 불가능하다(자세한 경위는
# docs/model_architecture.md 또는 이 대화 참고).

import numpy as np

from . import config
from .taxonomy import load_segment_texts


class SegmentEmbeddingLookup:
    def __init__(self, ids: list, vectors: np.ndarray):
        """ids/vectors: 실제 segment_id N개(패딩 행 제외). 여기서 패딩 행을 index 0에 추가한다."""
        vectors = np.asarray(vectors)
        self.vectors = np.vstack([np.zeros((1, vectors.shape[1]), dtype=vectors.dtype), vectors])
        self.id_to_index = {seg_id: i + 1 for i, seg_id in enumerate(ids)}

    def index_of(self, segment_id: str) -> int:
        """알 수 없는 segment_id(taxonomy 변경 등)는 0(=padding, EmbeddingBag 풀링에서 제외)으로 취급."""
        return self.id_to_index.get(segment_id, 0)

    def save(self, path=None) -> None:
        path = path or config.BERT_LOOKUP_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        ids = np.array(list(self.id_to_index.keys()))
        np.savez(path, ids=ids, vectors=self.vectors[1:])   # 패딩 행은 저장 안 함, load 시 재생성

    @classmethod
    def load(cls, path=None) -> "SegmentEmbeddingLookup":
        path = path or config.BERT_LOOKUP_PATH
        data = np.load(path, allow_pickle=False)
        return cls(list(data["ids"]), data["vectors"])

    @classmethod
    def build(cls, csv_path=None, model_name=None) -> "SegmentEmbeddingLookup":
        from sentence_transformers import SentenceTransformer

        texts = load_segment_texts(csv_path)
        ids = list(texts.keys())
        model = SentenceTransformer(model_name or config.BERT_MODEL_NAME)
        vectors = model.encode(
            [texts[i] for i in ids],
            batch_size=64,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return cls(ids, vectors)

    @classmethod
    def build_or_load(cls, path=None) -> "SegmentEmbeddingLookup":
        path = path or config.BERT_LOOKUP_PATH
        if path.exists():
            return cls.load(path)
        lookup = cls.build()
        lookup.save(path)
        return lookup
