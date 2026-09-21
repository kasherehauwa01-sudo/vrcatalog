import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class RecordingOperations:
    def __init__(self):
        self.created_indexes = []
        self.dropped_indexes = []

    def create_index(self, *args, **kwargs):
        self.created_indexes.append((args, kwargs))

    def drop_index(self, *args, **kwargs):
        self.dropped_indexes.append((args, kwargs))


class PropertyIndexMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.operations = RecordingOperations()
        alembic_stub = types.ModuleType("alembic")
        alembic_stub.op = cls.operations
        sqlalchemy_stub = types.ModuleType("sqlalchemy")
        sqlalchemy_stub.text = lambda expression: expression
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "0022_property_normalized_index.py"
        )
        spec = importlib.util.spec_from_file_location(
            "property_normalized_index_migration", migration_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Не удалось загрузить миграцию 0022")
        cls.migration = importlib.util.module_from_spec(spec)
        with patch.dict(
            sys.modules,
            {"alembic": alembic_stub, "sqlalchemy": sqlalchemy_stub},
        ):
            spec.loader.exec_module(cls.migration)

    def setUp(self):
        self.operations.created_indexes.clear()
        self.operations.dropped_indexes.clear()

    def test_upgrade_creates_fixed_size_hash_expression_index(self):
        self.migration.upgrade()

        self.assertEqual(len(self.operations.created_indexes), 1)
        args, kwargs = self.operations.created_indexes[0]
        self.assertEqual(kwargs, {})
        index_name, table_name, expressions = args
        self.assertEqual(index_name, "ix_product_properties_normalized_name_value")
        self.assertEqual(table_name, "product_properties")
        self.assertEqual(
            [str(expression) for expression in expressions],
            [
                "md5(lower(trim(name)))",
                "md5(lower(trim(value)))",
            ],
        )

    def test_downgrade_removes_hash_expression_index(self):
        self.migration.downgrade()

        self.assertEqual(
            self.operations.dropped_indexes,
            [
                (
                    ("ix_product_properties_normalized_name_value",),
                    {"table_name": "product_properties"},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
