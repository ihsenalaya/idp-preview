"""Migration tests — run alembic upgrade/downgrade and verify schema via information_schema."""
import os
import subprocess
import pytest
import psycopg2

pytestmark = pytest.mark.requires_db


def _run_alembic(cmd: str, db_url: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        ["alembic"] + cmd.split(),
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )
    return result


def _table_exists(db_url: str, table: str) -> bool:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s AND table_schema = 'public'",
        (table,),
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def _column_exists(db_url: str, table: str, column: str) -> bool:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s AND table_schema = 'public'",
        (table, column),
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def test_migration_001_creates_base_tables(db_url):
    result = _run_alembic("upgrade 001", db_url)
    assert result.returncode == 0, f"alembic upgrade 001 failed:\n{result.stderr}"
    assert _table_exists(db_url, "products")
    assert _table_exists(db_url, "categories")
    assert _table_exists(db_url, "orders")


def test_migration_002_creates_payments_table(db_url):
    result = _run_alembic("upgrade 002", db_url)
    assert result.returncode == 0, f"alembic upgrade 002 failed:\n{result.stderr}"
    assert _table_exists(db_url, "payments")


def test_migration_003_adds_discount_code(db_url):
    result = _run_alembic("upgrade 003", db_url)
    assert result.returncode == 0, f"alembic upgrade 003 failed:\n{result.stderr}"
    assert _column_exists(db_url, "orders", "discount_code")


def test_migration_003_downgrade_removes_discount_code(db_url):
    _run_alembic("upgrade head", db_url)
    result = _run_alembic("downgrade 002", db_url)
    assert result.returncode == 0, f"alembic downgrade 002 failed:\n{result.stderr}"
    assert not _column_exists(db_url, "orders", "discount_code")


def test_migration_002_downgrade_drops_payments(db_url):
    _run_alembic("upgrade head", db_url)
    _run_alembic("downgrade 002", db_url)
    result = _run_alembic("downgrade 001", db_url)
    assert result.returncode == 0, f"alembic downgrade 001 failed:\n{result.stderr}"
    assert not _table_exists(db_url, "payments")


def test_full_upgrade_head_succeeds(db_url):
    result = _run_alembic("upgrade head", db_url)
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"
