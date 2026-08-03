/* ============================================================
   06c_sample_candidate_table_media.sql (seed, 2026-07-31 신규)
   목적: 06b_create_candidate_table_media.sql로 만든 candidates_202606_media(13,195,163명)가
   너무 커서(profile/media/segment 재추출 + media_sequence 임베딩 재계산 규모가 감당 안 됨),
   media 단독 스코어링용으로 쓸 수 있게 5%로 표본 추출한다.

   방향 전환(사용자 확인, 2026-07-31): segment/combined 스코어링은 이 후보군에서는
   포기하고 media 단독 스코어링만 이 표본으로 진행한다 — segment 매칭 여부는 조건에서
   아예 뺀 채로 media 활동만 기준으로 뽑은 모집단이라(06b 참고), segment 데이터가 있는
   사람이 얼마나 될지 확인 안 된 상태다. 굳이 확인해서 combined까지 하려면 기존
   candidates_202606(segment 매칭, 664,684명)과 교집합을 잡는 방법도 있지만(이미 아는
   191,520명 근처로 줄어들 것으로 예상됨), 이번엔 그 경로 대신 순수 media 규모를
   다루기 좋은 크기로 줄이는 쪽을 택했다.

   샘플링: mod(crc32(...), 20) = 0 → 약 5%, 13,195,163명 → 약 66만 명 안팎(기존 segment
   후보 664,684명과 비슷한 규모라 비교하기 좋음). crc32는 부호 없는 해시라
   mod(hash,N)=0 형태를 쓰면 sampling_bugs.md의 signed-mod 버그를 피할 수 있다
   (CLAUDE.md 규칙 참고).

   전제: 06b_create_candidate_table_media.sql로 candidates_202606_media가 이미 있어야 함.
   ============================================================ */

CREATE TABLE candidates_202606_media_sample
WITH (format = 'PARQUET')
AS
SELECT device_ifa
FROM candidates_202606_media
WHERE mod(crc32(to_utf8(CAST(device_ifa AS VARCHAR))), 20) = 0;
