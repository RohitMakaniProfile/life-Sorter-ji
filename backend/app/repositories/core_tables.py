from __future__ import annotations

# Postgres-specific helper: advisory xact lock with hashtext() for per-conversation sequencing.
SQL_ADVISORY_CONVERSATION_LOCK = "SELECT pg_advisory_xact_lock(hashtext($1))"

SQL_INSERT_AGENT = """
    INSERT INTO agents (
        id, name, emoji, description,
        allowed_skill_ids, skill_selector_context, final_output_formatting_context,
        created_at, updated_at
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    ON CONFLICT (id) DO NOTHING
"""

SQL_INSERT_AGENT_RETURNING = """
    INSERT INTO agents (
        id, name, emoji, description,
        allowed_skill_ids, skill_selector_context, final_output_formatting_context,
        created_at, updated_at
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    RETURNING *
"""

SQL_INSERT_MESSAGE = """
    INSERT INTO messages (
        conversation_id, message_index, role, content, created_at, output_file, message
    ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
"""

SQL_SELECT_FORM_MESSAGES = """
    SELECT *
    FROM messages
    WHERE conversation_id = $1
      AND (message->>'formId') = $2
    ORDER BY message_index ASC
"""

SQL_SELECT_MESSAGE_BY_MESSAGE_ID = """
    SELECT message_index, message
    FROM messages
    WHERE conversation_id = $1 AND (message->>'messageId') = $2
    LIMIT 1
"""

SQL_UPDATE_MESSAGE_CONTENT = """
    UPDATE messages
    SET content = $3,
        output_file = COALESCE($4, output_file),
        message = $5::jsonb
    WHERE conversation_id = $1 AND message_index = $2
"""

SQL_UPDATE_MESSAGE_META = "UPDATE messages SET message = $3::jsonb WHERE conversation_id = $1 AND message_index = $2"
SQL_UPDATE_STAGE_OUTPUTS = (
    "UPDATE conversations SET last_stage_outputs = $2::jsonb, last_output_file = $3, updated_at = $4 WHERE id = $1"
)

SQL_INSERT_SKILL_CALL_RETURNING_ID = """
    INSERT INTO skill_calls (
        conversation_id, message_id, skill_id, run_id,
        input, state, output, started_at, created_at, updated_at
    ) VALUES ($1,$2,$3,$4,$5::jsonb,'running',$6::jsonb,$7,NOW(),NOW())
    RETURNING id
"""

SQL_RESET_SKILL_CALL_FOR_RETRY = """
    UPDATE skill_calls
    SET state       = 'running',
        error       = NULL,
        ended_at    = NULL,
        duration_ms = NULL,
        output      = '[]'::jsonb,
        run_id      = $2,
        message_id  = $3,
        input       = $4::jsonb,
        started_at  = NOW(),
        updated_at  = NOW()
    WHERE id = $1::bigint
"""

SQL_RELINK_SKILL_CALL_MESSAGE = "UPDATE skill_calls SET message_id = $2, updated_at = NOW() WHERE id = $1::bigint"
SQL_SELECT_SKILL_OUTPUT_BY_ID = "SELECT output FROM skill_calls WHERE id = $1::bigint"

SQL_APPEND_STREAMED_TEXT = """
    UPDATE skill_calls
    SET streamed_text = COALESCE(streamed_text, '') || $2,
        updated_at = NOW()
    WHERE id = $1::bigint
"""
SQL_ADD_STREAMED_TEXT_COLUMN = "ALTER TABLE skill_calls ADD COLUMN IF NOT EXISTS streamed_text TEXT NOT NULL DEFAULT ''"

SQL_SELECT_SKILL_TIMING_AND_OUTPUT = "SELECT started_at, output FROM skill_calls WHERE id = $1::bigint"
SQL_SELECT_DURATION_MS_FROM_STARTED_AT = "SELECT (EXTRACT(EPOCH FROM (NOW() - $1)) * 1000)::int AS ms"

SQL_UPDATE_SKILL_CALL_RESULT = """
    UPDATE skill_calls
    SET state = $2,
        error = $3,
        ended_at = $4,
        duration_ms = $5,
        output = $6::jsonb,
        updated_at = NOW()
    WHERE id = $1::bigint
"""

SQL_INSERT_PLAN_RUN_RETURNING = """
    INSERT INTO plan_runs (
        id, conversation_id, user_message_id, plan_message_id,
        status, plan_markdown, plan_json, created_at, updated_at
    ) VALUES ($1,$2,$3,$4,'draft',$5,$6::jsonb,$7,$8)
    RETURNING *
"""

SQL_CLAIM_PLAN_RUN_FOR_EXECUTION = """
    UPDATE plan_runs
    SET status = 'executing', updated_at = $2
    WHERE id = $1
      AND status IN ('draft', 'approved')
    RETURNING id
"""

SQL_ADD_PLAN_RUN_EXECUTION_MESSAGE_COLUMN = "ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS execution_message_id TEXT"
SQL_ADD_PLAN_RUN_ERROR_MESSAGE_COLUMN = "ALTER TABLE plan_runs ADD COLUMN IF NOT EXISTS error_message TEXT"

SQL_PROMOTE_SESSION_CONVERSATIONS = """
    UPDATE conversations
    SET user_id = $2, updated_at = NOW()
    WHERE session_id = $1
      AND (user_id IS NULL OR NULLIF(BTRIM(user_id::text), '') IS NULL)
"""

SQL_INSERT_SESSION_USER_LINK = """
    INSERT INTO session_user_links (session_id, user_id, linked_at)
    VALUES ($1, $2, NOW())
    ON CONFLICT (session_id, user_id) DO NOTHING
"""

SQL_CLEANUP_STALE_EXECUTING_PLANS = """
    UPDATE plan_runs
    SET status = 'interrupted',
        error_message = 'Process interrupted (backend restart). You can retry this plan.',
        updated_at = NOW()
    WHERE status = 'executing'
"""
