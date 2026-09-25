import importlib.util
from pathlib import Path
import unittest
from unittest.mock import call, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/0023_product_normalized_identifier_indexes.py"
)
SPEC = importlib.util.spec_from_file_location("product_identifier_indexes", MIGRATION_PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class ProductIdentifierIndexMigrationTests(unittest.TestCase):
    def test_upgrade_creates_both_functional_indexes(self):
        with patch.object(MIGRATION.op, "create_index") as create_index:
            MIGRATION.upgrade()

        self.assertEqual(create_index.call_count, 2)
        self.assertEqual(
            [item.args[:2] for item in create_index.call_args_list],
            [
                ("ix_products_normalized_code", "products"),
                ("ix_products_normalized_article", "products"),
            ],
        )
        self.assertEqual(
            [str(item.args[2][0]) for item in create_index.call_args_list],
            ["lower(trim(code))", "lower(trim(article))"],
        )

    def test_downgrade_drops_only_new_indexes(self):
        with patch.object(MIGRATION.op, "drop_index") as drop_index:
            MIGRATION.downgrade()

        self.assertEqual(drop_index.call_args_list, [
            call("ix_products_normalized_article", table_name="products"),
            call("ix_products_normalized_code", table_name="products"),
        ])
