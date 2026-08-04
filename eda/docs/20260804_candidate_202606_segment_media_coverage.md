# 6월 신규 유저 중 segment/media 보유 비율 — media 트랙을 추가한 이유

`eda/queries/22_candidate_202606_segment_media_coverage.sql` 실행 결과. "6월 신규 유저"는
`segment/03_create_candidate_table.sql`/`media/04_create_candidate_table_media.sql`이
공유하는 base 조건(seed 제외 + 2026-06 활동 + region=KR + OS=Android)만 적용한 모수다 —
segment 매칭이나 media 최소활동량 조건은 아직 적용하지 않은 상태.

## 결과

| | 인원수 | 비율(모수 대비) |
|---|---|---|
| 전체 6월 신규 유저(base) | 2,421,611 | 100.00% |
| segment 보유 | 586,748 | 24.23% |
| media 보유(top500, 30분dedup 5회 이상) | 805,302 | 33.25% |
| **segment와 media 둘 다 보유** | 150,288 | 6.21% |
| **segment 또는 media 중 하나라도 보유** | 1,241,762 | 51.28% |

## 해석

- **segment 단독으로는 신규 유저의 24.23%만 커버 가능**하다 — CLAUDE.md에 적어둔
  "1~2%대"는 seed 리스트 매칭까지 포함한 이전 추정치였고, 이번에 실측한 "segment
  taxonomy 자체 보유율"은 24.23%로 훨씬 높다(모수 정의가 달라진 데 따른 차이 — 이
  문서의 수치가 최신 기준).
- **media를 추가하면 커버리지가 51.28%까지 거의 2배로 늘어난다** — segment 단독 대비
  **+27.05%p(655,014명) 순증가**. 이 655,014명은 정확히 `with_media − with_both`
  (805,302 − 150,288)와도 일치해, "segment는 없지만 media는 있는" 사람 수와 동일하다는
  게 산술적으로도 확인된다.
- **두 그룹의 겹침은 작다**: 전체 대비 6.21%만 둘 다 보유하고, segment 보유자
  586,748명 중에서도 media까지 있는 사람은 25.6%뿐이다(150,288/586,748) — segment와
  media는 서로 다른 유저군을 잡아낸다는 뜻이며, `20260803_피엘라벤_media_KR_Android_필터_TiSASRec_재실험_요약.md`에서
  "media와 segment를 함께 갖고 있는 유저는 더욱 감소함"이라고 정성적으로 언급했던 부분의
  실측치가 이 6.21%/25.6%다.
- **결론**: segment 단독 추출로는 신규 유저의 4명 중 3명(75.77%)을 스코어링조차 못
  한다. media를 별도 트랙으로 추가하면 이 중 상당수(655,014명, 전체의 27.05%)를 추가로
  스코어링 가능한 후보로 편입할 수 있어, segment/media를 하나로 합치지 않고 독립된 두
  그룹으로 운영하기로 한 결정(`summary_note`의 관련 문서 참고)의 정량적 근거가 된다.

## 참고

- 쿼리: [`eda/queries/22_candidate_202606_segment_media_coverage.sql`](../queries/22_candidate_202606_segment_media_coverage.sql)
- `with_media`(805,302)는 `candidates_202606_media_sample`의 실제 인원(804,606)과 거의
  일치한다(소폭 차이는 재실행 시점의 데이터 갱신 때문으로 추정, 유의미한 차이 아님).
