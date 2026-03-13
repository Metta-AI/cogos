DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'cogos_process' AND column_name = 'code'
    ) THEN
        EXECUTE $migrate$
            WITH prompt_roots AS (
                SELECT
                    p.id,
                    string_agg(format('@{%s}', f.key), E'\n\n' ORDER BY roots.ordinality) AS refs
                FROM cogos_process p
                LEFT JOIN LATERAL (
                    SELECT value AS file_id_text, ordinality
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN p.files IS NOT NULL
                                 AND jsonb_typeof(p.files) = 'array'
                                 AND jsonb_array_length(p.files) > 0
                                THEN p.files
                            WHEN p.code IS NOT NULL
                                THEN jsonb_build_array(p.code::text)
                            ELSE '[]'::jsonb
                        END
                    ) WITH ORDINALITY AS roots(value, ordinality)
                ) roots ON TRUE
                LEFT JOIN cogos_file f ON f.id::text = roots.file_id_text
                GROUP BY p.id
            )
            UPDATE cogos_process p
            SET content = CASE
                WHEN prompt_roots.refs IS NULL OR prompt_roots.refs = '' THEN p.content
                WHEN COALESCE(p.content, '') = '' THEN prompt_roots.refs
                WHEN position(prompt_roots.refs IN p.content) > 0 THEN p.content
                ELSE prompt_roots.refs || E'\n\n' || p.content
            END
            FROM prompt_roots
            WHERE prompt_roots.id = p.id
        $migrate$;
    END IF;
END $$;

ALTER TABLE cogos_process DROP COLUMN IF EXISTS code;
ALTER TABLE cogos_process DROP COLUMN IF EXISTS files;
