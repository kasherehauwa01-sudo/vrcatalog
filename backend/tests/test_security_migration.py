import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


PATH = Path(__file__).parents[1] / "alembic/versions/0025_security_hardening.py"
SPEC = importlib.util.spec_from_file_location("security_migration", PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class SecurityMigrationTests(unittest.TestCase):
    def test_upgrade_adds_sessions_and_encrypted_password_without_dropping_plaintext(self):
        with patch.object(MIGRATION.op, "create_table") as create_table, patch.object(MIGRATION.op, "create_index"), patch.object(MIGRATION.op, "add_column") as add_column, patch.object(MIGRATION.op, "drop_column") as drop_column:
            MIGRATION.upgrade()
        create_table.assert_called_once()
        add_column.assert_called_once()
        drop_column.assert_not_called()

    def test_downgrade_removes_only_new_security_storage(self):
        with patch.object(MIGRATION.op, "drop_column") as drop_column, patch.object(MIGRATION.op, "drop_table") as drop_table:
            MIGRATION.downgrade()
        drop_column.assert_called_once_with("xml_server_settings", "encrypted_password")
        drop_table.assert_called_once_with("admin_sessions")
