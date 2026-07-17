import hashlib
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from backend.db import postgres


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Connection:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.executions = []

    async def execute(self, sql, *args):
        self.executions.append((sql, args))

    async def fetchrow(self, sql, version):
        checksum = self.existing.get(version)
        return {"checksum": checksum} if checksum else None

    def transaction(self):
        return _Transaction()


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class PostgresMigrationContract(unittest.IsolatedAsyncioTestCase):
    async def test_migration_is_locked_transactional_and_recorded(self):
        connection = _Connection()
        with patch.object(postgres, "get_pool", return_value=_Pool(connection)):
            self.assertTrue(await postgres.init_schema())

        rendered = "\n".join(sql for sql, _ in connection.executions)
        self.assertIn("pg_advisory_lock", rendered)
        self.assertIn("CREATE TABLE IF NOT EXISTS sessions", rendered)
        self.assertIn("INSERT INTO schema_migrations", rendered)
        self.assertIn("pg_advisory_unlock", rendered)

    async def test_applied_migration_checksum_must_not_change(self):
        migration = next(postgres._MIGRATIONS_DIR.glob("*.sql"))
        checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
        connection = _Connection({migration.stem: checksum})
        with patch.object(postgres, "get_pool", return_value=_Pool(connection)):
            self.assertTrue(await postgres.init_schema())

        rendered = "\n".join(sql for sql, _ in connection.executions)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS sessions", rendered)

    async def test_changed_applied_migration_fails_closed_and_unlocks(self):
        migration = next(postgres._MIGRATIONS_DIR.glob("*.sql"))
        connection = _Connection({migration.stem: "wrong-checksum"})
        with patch.object(postgres, "get_pool", return_value=_Pool(connection)):
            with self.assertRaisesRegex(RuntimeError, "changed after it was applied"):
                await postgres.init_schema()

        self.assertIn("pg_advisory_unlock", connection.executions[-1][0])


if __name__ == "__main__":
    unittest.main()
