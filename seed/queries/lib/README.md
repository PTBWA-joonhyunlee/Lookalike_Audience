# seed/queries/lib/

propfit(skp) 세그먼트 기반 임베딩 피처를 뽑는 재사용 라이브러리 쿼리. `seed/`의 segment
파이프라인(`seed/queries/segment/`)이 이 쿼리들을 device_ifa 조인으로 확장해서 쓴다.

| # | SQL | 역할 |
|---|---|---|
| 11 | `11_user_embedding_features.sql` | skp 세그먼트 기반 임베딩 피처(성별 스칼라/연령대/거주/관심아 3그룹) — `seed/queries/segment/`가 확장해서 씀 |

**2026-08-26 삭제**: `02_user_media.sql`(media_sequence 입력, `seed/queries/media/`가
확장해서 씀)을 media 트랙 전체 삭제와 함께 지웠다. 필요해지면 git 히스토리에서 복구 가능.

11의 출력은 `embedding/segment_features/build_features.py`가 읽어 최종 학습 피처(BERT
풀링 벡터 등)로 변환한다.

**2026-08-04 삭제**: `01_user_profile.sql`(bid log 네이티브 프로필 — os/region/app_bundle/
carrier)과 이를 확장한 `04a_seed_profile.sql`/`05a_pool_profile.sql`/
`07a_candidate_profile.sql`을 삭제했다 — segment/media 두 트랙 중 어디에도 속하지 않는
피처였고(profile 임베딩 모델 자체가 없음), region/OS 필터 결정에 쓰인 이후로는 재사용할
계획이 없어서다. 필요해지면 git 히스토리에서 복구 가능.

이 쿼리들 자체를 확정하기까지의 진단/EDA 쿼리(ID 공간 크로스워크 검증, 세그먼트 커버리지
실측 등)와 그 결론은 `eda/queries/00~08`, `eda/docs/`에 있다.
