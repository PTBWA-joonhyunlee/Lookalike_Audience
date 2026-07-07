SELECT
    SUBSTR(CAST(p.created_at AS VARCHAR), 1, 10) AS dt,
    hour,
    p.cmp_no,
    p.ctv_media,
    p.content_id,
    pf.title AS content_title,
    p.media_id,
    COUNT(DISTINCT CASE WHEN p.log_type = 'i' THEN p.req_id END) AS post_imp,
    COUNT(DISTINCT CASE WHEN p.log_type = 'v_complete' THEN p.req_id END) AS v_complete,
    COUNT(DISTINCT CASE WHEN p.log_type = 'v_complete' THEN p.ifa END) AS stp_adid,
    COUNT(DISTINCT CASE WHEN p.log_type = 'v_complete' THEN p.request_ip END) AS stp_ip
FROM "prod-ptbwa-dw"."addi_postback_log" p
LEFT JOIN "ptbwa-metadata"."apm_channel_name_mapping_new" pf
    ON CAST(p.content_id AS VARCHAR) = CAST(pf.content_id AS VARCHAR)
GROUP BY
    1, 2, 3, 4, 5,6,7
;