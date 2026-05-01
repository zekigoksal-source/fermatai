-- 25.37+ (Neo audit #8 + #11): Routing stats admin/selfdev filtreleme view'leri
-- Gerçek kullanıcı performansı admin (Neo) trafiğinden ayrı görünür.

-- ═══════════════════════════════════════════════════════════════════════
-- View 1: Gerçek kullanıcı routing (admin + selfdev hariç)
-- Neo'nun dev sırasındaki testleri, selfdev_* tool çağrıları çıkarılır.
-- ═══════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW fermat.real_user_routing_stats AS
SELECT
    id, created_at, phone, role, message, response_source, response_ms,
    response_grade, handler_name, decision_trace, tools_called, prompt_blocks
FROM fermat.routing_stats
WHERE
    -- Admin (Neo) hariç
    phone NOT IN ('905051256802')
    -- Selfdev tool kullanımı varsa hariç (admin dev path)
    AND NOT (tools_called && ARRAY[
        'selfdev_read_file', 'selfdev_grep_repo', 'selfdev_list_dir',
        'selfdev_read_logs', 'selfdev_git_diff', 'selfdev_git_log',
        'selfdev_git_blame', 'selfdev_search_atlas_history',
        'selfdev_write_brief', 'selfdev_list_briefs', 'selfdev_get_brief',
        'selfdev_apply_brief', 'selfdev_list_drafts', 'selfdev_read_draft',
        'selfdev_delete_draft', 'selfdev_draft_to_local_branch',
        'selfdev_push_branch', 'selfdev_list_bot_branches', 'selfdev_branch_status',
        'selfdev_delete_branch', 'selfdev_create_pr_draft', 'selfdev_get_pr_status',
        'selfdev_pr_comment', 'selfdev_close_pr', 'selfdev_full_pipeline'
    ]);

COMMENT ON VIEW fermat.real_user_routing_stats IS
'25.37+ Audit #8: Admin (Neo dev test) + selfdev_* tool çağrıları hariç gerçek kullanıcı routing dağılımı';

-- ═══════════════════════════════════════════════════════════════════════
-- View 2: Admin / dev session (Neo + selfdev sadece)
-- ═══════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW fermat.admin_dev_routing_stats AS
SELECT
    id, created_at, phone, role, message, response_source, response_ms,
    response_grade, handler_name, decision_trace, tools_called, prompt_blocks,
    CASE
        WHEN tools_called && ARRAY['selfdev_read_file', 'selfdev_grep_repo',
            'selfdev_write_brief', 'selfdev_apply_brief', 'selfdev_full_pipeline']
        THEN 'selfdev'
        ELSE 'admin_normal'
    END AS session_kind
FROM fermat.routing_stats
WHERE phone = '905051256802';

COMMENT ON VIEW fermat.admin_dev_routing_stats IS
'25.37+ Audit #8+#11: Neo admin trafiği + selfdev kategorize';

-- ═══════════════════════════════════════════════════════════════════════
-- View 3: Routing dashboard summary (gerçek kullanıcı bazlı)
-- ═══════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW fermat.routing_dashboard_real AS
SELECT
    response_source,
    COUNT(*) AS msg_count,
    ROUND(AVG(response_ms))::int AS avg_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_ms)::int AS p50,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_ms)::int AS p95,
    MAX(response_ms) AS max_ms,
    DATE(created_at) AS day
FROM fermat.real_user_routing_stats
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY response_source, DATE(created_at)
ORDER BY day DESC, msg_count DESC;
