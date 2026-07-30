# seed/queries/lib/

propfit(skp) 세그먼트 기반 임베딩 피처를 뽑는 재사용 라이브러리 쿼리. `seed/`의 파이프라인
(`seed/queries/01~07*.sql`)이 이 3개를 device_ifa 조인으로 확장해서 쓴다 — postback 트랙을
시작하면 그쪽에서도 그대로 재사용할 예정.

| # | SQL | 역할 |
|---|---|---|
| 01 | `01_user_profile.sql` | bid log 네이티브 프로필(os/region/app_bundle/carrier) |
| 02 | `02_user_media.sql` | media_sequence 입력(device_ifa × media × ts) |
| 11 | `11_user_embedding_features.sql` | skp 세그먼트 기반 임베딩 피처(성별 스칼라/연령대/거주/관심아 3그룹) |

01/02는 `device_ifa` 키의 bid log 파생 피처, 11은 같은 키의 skp 세그먼트 파생 피처 —
나중에 device_ifa로 합친다. 11의 출력은 `embedding/segment_features/build_features.py`가
읽어 최종 학습 피처(BERT 풀링 벡터 등)로 변환한다.

이 3개 쿼리 자체를 확정하기까지의 진단/EDA 쿼리(ID 공간 크로스워크 검증, 세그먼트 커버리지
실측 등)와 그 결론은 `eda/queries/00~08`, `eda/docs/`에 있다.
