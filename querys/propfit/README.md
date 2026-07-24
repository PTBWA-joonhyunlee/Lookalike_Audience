# querys/propfit/

propfit(skp) 세그먼트 기반 임베딩 피처를 뽑는 쿼리. 실제로 실행/재실행할 쿼리는 아래 3개뿐이고,
나머지는 이 3개를 확정하기까지의 진단/EDA 쿼리라 `_archived/`로 옮겼다(결론은 이 문서와
`docs/_archive/`에 남아있음).

| # | SQL | 역할 |
|---|---|---|
| 01 | `01_user_profile.sql` | bid log 네이티브 프로필(os/region/app_bundle/carrier) |
| 02 | `02_user_media.sql` | media_sequence 입력(device_ifa × media × ts) |
| 11 | `11_user_embedding_features.sql` | skp 세그먼트 기반 임베딩 피처(성별 스칼라/연령대/거주/관심아 3그룹) |

01/02는 `device_ifa` 키의 bid log 파생 피처, 11은 같은 키의 skp 세그먼트 파생 피처 —
나중에 device_ifa로 합친다. 11의 출력은 `embedding/segment_features/build_features.py`가
읽어 최종 학습 피처(BERT 풀링 벡터 등)로 변환한다.

## `_archived/` — 결론이 난 진단/EDA 쿼리

| SQL | 확인한 것 | 결론 반영 위치 |
|---|---|---|
| `00_id_mapping_check.sql` | `skp.ad_id`가 크로스워크 없이 바로 `device_ifa` 공간임(vs `ptbwa_tg`는 `ptbwa_skb` 경유 필요) | `03`(현 아카이브)·`11`의 `ad_id AS device_ifa` 직접 alias 근거. [`docs/_archive/202607240935.md`](../../docs/_archive/202607240935.md) |
| `03_user_segments.sql` | skp 원시 `segments`(세미콜론 구분 ID) 풀 + 세그먼트 카테고리 매핑 발견, EmbeddingBag vs 사전학습 BERT 임베딩 방식 재검토 | 그룹/스코어링 로직이 `11`로 확정 반영됨(원시 풀 쿼리 자체는 더 이상 필요 없음) |
| `04_coverage_check.sql` | bid 모집단 대비 `ptbwa_tg` 도달률 0.003%(2,500명) — 사실상 무의미 | `01`에서 `ptbwa_tg` 조인 제거 근거. [`docs/_archive/202607240935.md`](../../docs/_archive/202607240935.md) |
| `05_segment_demographics_check.sql` | skp 성별(모델링)/연령대 세그먼트가 `ptbwa_tg` 대비 ~3,500배 나은 커버리지(12.3%) | `ptbwa_tg` 완전 대체 결정 근거. [`docs/_archive/202607240935.md`](../../docs/_archive/202607240935.md) |
| `06_create_segment_category_table.sql` | `세그먼트_카테고리.csv`를 Athena 테이블(`"prod-ptbwa-dw"."segment_category"`)로 적재 성공 | 이후 `taxonomy.py`가 로컬 CSV를 직접 읽는 것으로 설계가 확정되어 프로덕션 피처 빌드에서는 이 Athena 테이블을 쓰지 않음(SQL에서 세그먼트 이름 조인이 다시 필요해지면 재사용 가능) |
| `07_segment_wide_features_missingness.sql` | 성별/연령대/거주/제품 관심사/콘텐츠 관심사/기타 6개 그룹 결측률 | `11`의 6개 그룹 정의·ID 목록 출처. [`docs/_archive/202607241426_segment_distribution_report.md`](../../docs/_archive/202607241426_segment_distribution_report.md) |
| `08_product_content_interest_combined_coverage.sql` | 관심아 3그룹(제품/콘텐츠/기타)의 인구 겹침 — 기타가 제품·콘텐츠를 98%+ 포함 | "인구 겹침 ≠ 정보 겹침" 판단 근거 → `11`/`build_features.py`에서 3그룹을 합치지 않고 공유 임베딩+분리 풀링으로 설계 |
| `09_group_bucket_coverage.sql` | 인구통계/거주/관심아 묶음 단위 커버리지 | [`docs/_archive/202607241426_segment_distribution_report.md`](../../docs/_archive/202607241426_segment_distribution_report.md) |
| `10_group_value_distribution.sql` | 그룹별 개별 세그먼트 값 분포(983행) | `data/sample/세그먼트id별분포.csv` 산출, [`docs/_archive/202607241426_segment_distribution_report.md`](../../docs/_archive/202607241426_segment_distribution_report.md) |
