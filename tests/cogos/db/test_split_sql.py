"""Tests for _split_sql in migrations."""

from cogos.db.migrations import _split_sql


def test_split_sql_ignores_dollar_signs_in_comments():
    """Regression: $$ inside SQL comments should not toggle dollar-block mode."""
    sql = """\
-- This comment mentions DO $$ block syntax
ALTER TABLE foo DROP CONSTRAINT IF EXISTS bar;
CREATE UNIQUE INDEX IF NOT EXISTS idx_foo ON foo (col);
"""
    stmts = _split_sql(sql)
    # Should produce two statements, not one combined block
    non_empty = [s.strip() for s in stmts if s.strip()]
    assert len(non_empty) == 2
    assert "ALTER TABLE" in non_empty[0]
    assert "CREATE UNIQUE INDEX" in non_empty[1]


def test_split_sql_dollar_blocks_still_work():
    """Real $$ blocks in non-comment lines should still be respected."""
    sql = """\
CREATE OR REPLACE FUNCTION foo() RETURNS TRIGGER AS $$
BEGIN
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
    stmts = _split_sql(sql)
    non_empty = [s.strip() for s in stmts if s.strip()]
    assert len(non_empty) == 1
    assert "CREATE OR REPLACE FUNCTION" in non_empty[0]
    assert "RETURN NEW" in non_empty[0]


def test_split_sql_basic():
    """Basic splitting on semicolons."""
    sql = "ALTER TABLE a ADD COLUMN x INT;\nALTER TABLE b ADD COLUMN y INT;"
    stmts = _split_sql(sql)
    non_empty = [s.strip() for s in stmts if s.strip()]
    assert len(non_empty) == 2
