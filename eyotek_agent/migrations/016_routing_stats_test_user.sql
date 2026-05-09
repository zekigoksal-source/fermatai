-- 25.42 (Bulgu F, 9 May 2026): test_user flag — Neo testi vs gercek kullanici ayrimi
--
-- Neo direktifi: "Test ve gerçek kullaniciyi sistem ayırt etmeli routing değerleri için.
-- Testleri de kullanması mantıklı veri anlamında değerli, fakat onun dışında
-- verilerin test olduğunu sistem bilmeli."
--
-- 9 May konusu: 905309356389 numarasi gece 235 mesaj burst (render araç testi),
-- routing_stats'i yaniltici hale getirdi (%57 Claude). Bu kayitlar is_test_user=true
-- olarak isaretlenirse, real_user_routing_stats view'i otomatik filtreler.

ALTER TABLE fermat.routing_stats
    ADD COLUMN IF NOT EXISTS is_test_user BOOLEAN DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_routing_stats_test_user
    ON fermat.routing_stats (is_test_user, created_at DESC)
    WHERE is_test_user = false;  -- partial index — gercek kullanicilar (sik sorgu)

-- Eski kayitlari (9 May test burst'u) retroaktif isaretle
-- 905309356389 — gece 00:02-01:05 render araç testi
UPDATE fermat.routing_stats
SET is_test_user = true
WHERE phone = '905309356389'
  AND created_at::date = '2026-05-09';

-- ═══════════════════════════════════════════════════════════════════════
-- View 1 update — real_user_routing_stats: test_user da hariç
-- ═══════════════════════════════════════════════════════════════════════
DROP VIEW IF EXISTS fermat.real_user_routing_stats CASCADE;

CREATE OR REPLACE VIEW fermat.real_user_routing_stats AS
SELECT
    id, created_at, phone, role, message, response_source, response_ms,
    response_grade, handler_name, decision_trace, tools_called, prompt_blocks,
    is_test_user
FROM fermat.routing_stats
WHERE
    -- Admin (Neo) hariç
    phone NOT IN ('905051256802')
    -- 25.42 (Bulgu F): test kullanici hariç
    AND COALESCE(is_test_user, false) = false
    -- Selfdev tool kullanımı varsa hariç (admin dev path)
    AND NOT (COALESCE(tools_called, ARRAY[]::text[]) && ARRAY[
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
'25.42 update: Admin + test_user + selfdev_* tool çağrıları hariç gerçek kullanıcı routing dağılımı';

-- ═══════════════════════════════════════════════════════════════════════
-- View 2: test_user_routing_stats — sadece test verisi (QA dashboard icin)
-- ═══════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW fermat.test_user_routing_stats AS
SELECT
    id, created_at, phone, role, message, response_source, response_ms,
    response_grade, handler_name, decision_trace, tools_called, prompt_blocks
FROM fermat.routing_stats
WHERE COALESCE(is_test_user, false) = true;

COMMENT ON VIEW fermat.test_user_routing_stats IS
'25.42: Sadece test kullanici (905309356389 vb) trafigi — QA dashboard icin ayri raporlama';
