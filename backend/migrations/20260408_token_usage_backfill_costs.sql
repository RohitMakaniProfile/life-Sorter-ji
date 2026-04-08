-- Backfill token_usage costs for existing rows where cost is still NULL.
-- Keeps backend as authoritative source of pricing.

UPDATE token_usage
SET
    cost_usd = ROUND((
        (GREATEST(COALESCE(input_tokens, 0), 0)::numeric *
            CASE
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4.1%' THEN (5.0 / 1000000.0)
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4o-mini%' THEN (0.15 / 1000000.0)
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-opus-4-6%' THEN (15.0 / 1000000.0)
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-sonnet-4-6%' THEN (3.0 / 1000000.0)
                ELSE 0
            END
        ) +
        (GREATEST(COALESCE(output_tokens, 0), 0)::numeric *
            CASE
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4.1%' THEN (15.0 / 1000000.0)
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4o-mini%' THEN (0.6 / 1000000.0)
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-opus-4-6%' THEN (75.0 / 1000000.0)
                WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-sonnet-4-6%' THEN (15.0 / 1000000.0)
                ELSE 0
            END
        )
    ), 6),
    cost_inr = ROUND((
        (
            (GREATEST(COALESCE(input_tokens, 0), 0)::numeric *
                CASE
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4.1%' THEN (5.0 / 1000000.0)
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4o-mini%' THEN (0.15 / 1000000.0)
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-opus-4-6%' THEN (15.0 / 1000000.0)
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-sonnet-4-6%' THEN (3.0 / 1000000.0)
                    ELSE 0
                END
            ) +
            (GREATEST(COALESCE(output_tokens, 0), 0)::numeric *
                CASE
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4.1%' THEN (15.0 / 1000000.0)
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%gpt-4o-mini%' THEN (0.6 / 1000000.0)
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-opus-4-6%' THEN (75.0 / 1000000.0)
                    WHEN LOWER(COALESCE(model_name, '')) LIKE '%claude-sonnet-4-6%' THEN (15.0 / 1000000.0)
                    ELSE 0
                END
            )
        ) * 94.0
    ), 2)
WHERE cost_inr IS NULL
  AND (
      LOWER(COALESCE(model_name, '')) LIKE '%gpt-4.1%'
      OR LOWER(COALESCE(model_name, '')) LIKE '%gpt-4o-mini%'
      OR LOWER(COALESCE(model_name, '')) LIKE '%claude-opus-4-6%'
      OR LOWER(COALESCE(model_name, '')) LIKE '%claude-sonnet-4-6%'
  );

