import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/0024_add_history_snapshots.py"
SPEC = importlib.util.spec_from_file_location("history_snapshot_migration", MIGRATION_PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class HistorySnapshotMigrationTests(unittest.TestCase):
    def test_upgrade_creates_normalized_history_tables(self):
        with patch.object(MIGRATION.op, "create_table") as create_table, patch.object(MIGRATION.op, "create_index"):
            MIGRATION.upgrade()

        self.assertEqual(
            [item.args[0] for item in create_table.call_args_list],
            ["history_settings", "history_snapshots", "history_snapshot_items", "history_snapshot_item_prices"],
        )

    def test_downgrade_drops_children_before_parents(self):
        with patch.object(MIGRATION.op, "drop_table") as drop_table:
            MIGRATION.downgrade()

        self.assertEqual(
            [item.args[0] for item in drop_table.call_args_list],
            ["history_snapshot_item_prices", "history_snapshot_items", "history_snapshots", "history_settings"],
        )
