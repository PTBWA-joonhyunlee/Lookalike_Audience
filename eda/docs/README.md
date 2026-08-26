# eda/ — 진단/EDA 쿼리와 분석 결과

`seed/` 트랙에서 쓰는 피처 추출 쿼리(`seed/queries/lib/`)를
확정하기까지의 진단·EDA 작업. 실행 순서 자체보다 "무엇을 확인했고 결론이 뭐였는지"가
중요해서 쿼리(`eda/queries/`)와 분석 문서(`eda/docs/`)를 시간순으로 둔다.

## 문서

| 문서 | 내용 |
|---|---|
| [`202607240935.md`](202607240935.md) | 2026-07-24: propfit 소스 피처 설계 검토(bid log 교체, ID 크로스워크 첫 진단, gender/age 커버리지 실측 — `ptbwa_tg` 폐기 근거) |
| [`segment_distribution_report.md`](segment_distribution_report.md) / [`.html`](segment_distribution_report.html) | 2026-07-24: skp 세그먼트 그룹별(성별/연령대/거주/관심사) 분포·CV 분석 — `11_user_embedding_features.sql`의 6개 그룹 정의·`max_len` 근거 |
| [`id_space_crosswalk.md`](id_space_crosswalk.md) | 2026-07-29: 피엘라벤 seed가 `skp.ad_id`와 직접 안 붙던 이유(플랫폼 ID 공간 불일치) 추적 — `skb.platform_ad_id → ad_id` 크로스워크 확정까지 |
| [`sampling_bugs.md`](sampling_bugs.md) | 2026-07-30: pool 표본 4억 행 폭증(Trino `mod()` 부호 버그) + 후보 세그먼트 매칭률 1.6%(대소문자 가설 기각, 정상 특성으로 결론) |

## 쿼리 (`eda/queries/`)

2026-08-26에 용도별로 하위 폴더 두 개로 재정리했다(번호는 각 폴더 안에서 01부터 다시
매김 — 이전 평면 번호와의 대응은 각 파일 헤더의 "구 eda/queries/NN" 주석 참고):

- **`segment_coverage/`**(01~11) — skp 세그먼트 보유율·값 분포 확인용. 2026-07-24 propfit
  소스 피처 설계 검토(`202607240935.md`/`segment_distribution_report.md` 배경, 舊 00~08)
  + 이후 전체/seed 모집단 커버리지 실측(舊 21, 26, 27).
- **`id_space_check/`**(01~15) — seed device_ifa가 어떤 ID 공간에 있는지(raw GAID 직접 vs
  skb 크로스워크 필요) 확인용. 2026-07-29~30 피엘라벤 seed ID 공간/표본 조사
  (`id_space_crosswalk.md`/`sampling_bugs.md` 배경, 舊 00, 09~20) + 이후 신규 seed마다
  반복 실행하는 `pipeline/generate_seed_queries.py` 자동 생성 쿼리(舊 28, 29 — je/shoplinker).

media 트랙 관련 진단 쿼리(舊 22~25, "6월 신규 유저" segment/media 커버리지·top30 미디어
분석)는 2026-08-26 media 트랙 삭제와 함께 제거했다(필요하면 git 히스토리에서 복구 가능,
`eda/docs/20260804_candidate_202606_segment_media_coverage.md`는 결론 기록으로 남겨둠).

## `assets/`

`_gen_segment_report.py`가 같은 폴더의 `세그먼트id별분포.csv`를 읽어 `concentration_curve.png`/
`distribution_shape.png`/`segment_group_summary_stats.csv`를 만든다 — `segment_distribution_report.md`가
참조하는 생성 스크립트/산출물.
