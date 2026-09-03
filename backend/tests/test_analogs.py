import json
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import AnalogSelectionSetting, Price, Product, ProductImage, ProductProperty
from app.services.analogs import find_product_analogs


class AnalogSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        for model in (ProductImage, Price, ProductProperty, Product, AnalogSelectionSetting):
            self.db.query(model).delete()
        self.db.add(AnalogSelectionSetting(
            primary_properties_json=json.dumps(["Материал", "Цвет"], ensure_ascii=False),
            minimum_similarity=0,
            maximum_analogs=10,
        ))
        self.source = self.product("SRC", "Посуда", "Кастрюля", "Сталь", "Черный")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def product(self, code, section, product_type, material=None, color=None):
        product = Product(
            code=code, article=code, name=f"Товар {code}", section=section,
            product_type=product_type, material=material, color=color,
            quantity=1, search_text="",
        )
        self.db.add(product)
        self.db.flush()
        return product

    def test_full_match_and_self_exclusion(self):
        candidate = self.product("MATCH", "Посуда", "Кастрюля", "Сталь", "Черный")
        self.db.commit()

        result = find_product_analogs(self.db, self.source.id)

        self.assertEqual([item.product.id for item in result], [candidate.id])
        self.assertEqual(result[0].similarity, 100)
        self.assertIn("Материал", result[0].matched)

    def test_different_category_is_never_considered(self):
        self.product("OTHER", "Сад", "Кастрюля", "Сталь", "Черный")
        self.db.commit()
        self.assertEqual(find_product_analogs(self.db, self.source.id), [])

    def test_same_type_is_selected_before_category_fallback(self):
        same_type = self.product("SAME-TYPE", "Посуда", "Кастрюля", "Сталь", "Белый")
        better_other_type = self.product("OTHER-TYPE", "Посуда", "Сковорода", "Сталь", "Черный")
        self.db.commit()

        result = find_product_analogs(self.db, self.source.id)

        self.assertEqual([item.product.id for item in result[:2]], [same_type.id, better_other_type.id])

    def test_primary_match_has_more_weight_than_secondary_match(self):
        primary = self.product("PRIMARY", "Посуда", "Кастрюля", "Сталь", "Белый")
        secondary = self.product("SECONDARY", "Посуда", "Кастрюля", "Алюминий", "Белый")
        self.source.manufacturer = "Завод"
        secondary.manufacturer = "Завод"
        self.db.commit()

        result = find_product_analogs(self.db, self.source.id)
        scores = {item.product.id: item.similarity for item in result}

        self.assertGreater(scores[primary.id], scores[secondary.id])

    def test_missing_candidate_property_is_excluded_from_weighting(self):
        candidate = self.product("NO-COLOR", "Посуда", "Кастрюля", "Сталь", None)
        self.db.commit()

        selected = find_product_analogs(self.db, self.source.id)[0]

        self.assertEqual(selected.product.id, candidate.id)
        self.assertEqual(selected.similarity, 100)
        self.assertNotIn("Цвет", selected.matched)
        self.assertNotIn("Цвет", selected.unmatched)

    def test_missing_source_property_is_excluded_from_weighting(self):
        self.source.material = None
        candidate = self.product("EXTRA-MATERIAL", "Посуда", "Кастрюля", "Алюминий", "Черный")
        self.db.commit()

        selected = find_product_analogs(self.db, self.source.id)[0]

        self.assertEqual(selected.product.id, candidate.id)
        self.assertEqual(selected.similarity, 100)
        self.assertNotIn("Материал", selected.matched)
        self.assertNotIn("Материал", selected.unmatched)

    def test_secondary_characteristic_also_contributes_to_score(self):
        candidate = self.product("SECONDARY", "Посуда", "Кастрюля", "Алюминий", "Белый")
        self.source.manufacturer = "Завод"
        candidate.manufacturer = "Завод"
        self.db.commit()

        result = find_product_analogs(self.db, self.source.id)
        selected = next(item for item in result if item.product.id == candidate.id)

        self.assertGreater(selected.similarity, 0)
        self.assertIn("Производитель", selected.matched)

    def test_many_matching_properties_produce_full_match(self):
        candidate = self.product("MANY", "Посуда", "Кастрюля", "Сталь", "Черный")
        for index in range(30):
            self.db.add_all([
                ProductProperty(product_id=self.source.id, name=f"Свойство {index}", value=f"Значение {index}"),
                ProductProperty(product_id=candidate.id, name=f"Свойство {index}", value=f"Значение {index}"),
            ])
        self.db.commit()

        result = find_product_analogs(self.db, self.source.id)

        self.assertEqual(result[0].similarity, 100)
        self.assertEqual(len(result[0].matched), 33)

    def test_minimum_similarity_and_limit_are_applied(self):
        setting = self.db.query(AnalogSelectionSetting).one()
        setting.minimum_similarity = 100
        setting.maximum_analogs = 1
        winner = self.product("WIN", "Посуда", "Кастрюля", "Сталь", "Черный")
        self.product("LOW", "Посуда", "Кастрюля", "Сталь", "Белый")
        self.db.commit()

        result = find_product_analogs(self.db, self.source.id)

        self.assertEqual([item.product.id for item in result], [winner.id])

    def test_product_without_characteristics_returns_no_matches_above_zero(self):
        source = self.product("EMPTY", "Посуда", None)
        self.db.query(AnalogSelectionSetting).one().minimum_similarity = 1
        self.db.commit()
        self.assertEqual(find_product_analogs(self.db, source.id), [])

    def test_query_count_does_not_depend_on_catalog_size_outside_category(self):
        for index in range(200):
            self.product(f"OUT-{index}", "Другая категория", "Кастрюля", "Сталь", "Черный")
        self.product("IN", "Посуда", "Кастрюля", "Сталь", "Черный")
        self.db.commit()
        statements = []

        def count_queries(*_args):
            statements.append(1)

        event.listen(self.engine, "before_cursor_execute", count_queries)
        try:
            result = find_product_analogs(self.db, self.source.id)
        finally:
            event.remove(self.engine, "before_cursor_execute", count_queries)

        self.assertEqual(len(result), 1)
        # Исходный товар, настройки, кандидаты и данные показа ТОП выполняются
        # пакетно; число SQL-запросов не растёт вместе с количеством товаров.
        self.assertLessEqual(len(statements), 8)


if __name__ == "__main__":
    unittest.main()
