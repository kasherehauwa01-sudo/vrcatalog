"""Local Vite + Playwright/Chromium UI check. All backend requests are mocked."""
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect

base = os.environ.get('CATALOG_TEST_URL', 'http://localhost:5173/vr/catalog/')
artifacts = Path(os.environ.get('CATALOG_TEST_ARTIFACTS', '/tmp/excel-columns-previews'))
artifacts.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    for width, height in ((1440, 1000), (390, 844)):
        context = browser.new_context(viewport={'width': width, 'height': height}, service_workers='block')
        page = context.new_page()
        exports, errors = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def api(route):
            path = urlsplit(route.request.url).path
            if path.endswith('/meta'):
                result = {'product_count': 3}
            elif path.endswith('/filters'):
                result = {'filters': {}, 'section_tree': []}
            elif path.endswith('/products/search'):
                result = {'items': [], 'pagination': {'page': 1, 'pageSize': 100, 'totalItems': 3, 'totalPages': 1}}
            elif path.endswith('/warehouses'):
                result = [{'id': i, 'code': f'WH{i}', 'name': name} for i, name in enumerate(['Авиаторов Зал+Склад', 'Диамант', 'Привоз', 'Ахтубинск', 'Козловская', 'Бахтурова'])]
            elif path.endswith('/admin/session'):
                result = {'authenticated': True, 'csrf_token': 'test-token'}
            elif path.endswith('/exports/xlsx'):
                exports.append(route.request.url)
                result = {'job_id': 'test-export', 'status': 'processing'}
            elif path.endswith('/exports/xlsx/test-export'):
                result = {'status': 'error', 'error': 'Тестовая ошибка экспорта'}
            else:
                result = []
            route.fulfill(json=result)
        page.route('**/vr/catalog/api/**', api)
        page.goto(base)
        page.get_by_role('button', name='Скачать Excel', exact=True).click()
        dialog = page.get_by_role('dialog', name='Колонки для Excel')
        expect(dialog).to_be_visible()
        box = dialog.bounding_box()
        assert box['width'] == width and box['height'] == height
        expect(dialog.get_by_role('checkbox', name='Наименование', exact=True)).to_be_checked()
        dialog.get_by_role('button', name='Снять все', exact=True).click()
        expect(dialog.get_by_role('button', name='Скачать Excel', exact=True)).to_be_disabled()
        dialog.get_by_role('checkbox', name='Выбрать всю группу: Фото и ссылки', exact=True).check()
        expect(dialog.get_by_role('checkbox', name='Фото', exact=True)).to_be_checked()
        dialog.get_by_role('checkbox', name='Фото', exact=True).uncheck()
        expect(dialog.get_by_role('checkbox', name='Ссылка на фото', exact=True)).to_be_checked()
        expect(dialog.get_by_role('checkbox', name='Ссылка на сайт', exact=True)).to_be_checked()
        dialog.get_by_role('checkbox', name='Код', exact=True).check()
        expect(dialog.get_by_text('Выбрано колонок: 3', exact=True)).to_be_visible()
        dialog.locator('.MuiDialogContent-root').evaluate('(node) => node.scrollTop = 0')
        page.wait_for_timeout(350)
        assert dialog.evaluate('(node) => node.scrollWidth <= node.clientWidth')
        page.screenshot(path=str(artifacts / f'excel-{width}.png'))
        dialog.get_by_role('button', name='Скачать Excel', exact=True).click()
        expect(dialog.get_by_role('checkbox', name='Ссылка на сайт', exact=True)).to_be_disabled()
        expect(dialog.get_by_role('alert')).to_have_text('Тестовая ошибка экспорта', timeout=10000)
        assert len(exports) == 1
        assert set(parse_qs(urlsplit(exports[0]).query)['column']) == {'code', 'image_url', 'site_url'}
        expect(dialog.get_by_role('checkbox', name='Ссылка на сайт', exact=True)).to_be_enabled()
        dialog.get_by_role('button', name='Стандартный набор', exact=True).click()
        expect(dialog.get_by_role('checkbox', name='Ссылка на сайт', exact=True)).not_to_be_checked()
        expect(dialog.get_by_role('checkbox', name='Раздел', exact=True)).to_be_checked()
        dialog.get_by_role('checkbox', name='Выбрать всю группу: Цены', exact=True).check()
        dialog.get_by_role('checkbox', name='Форма для акции месяца', exact=True).check()
        expect(dialog.get_by_role('checkbox', name='ЦенаОптовая', exact=True)).to_be_checked()
        expect(dialog.get_by_role('checkbox', name='ЦенаРозничная', exact=True)).not_to_be_checked()
        expect(dialog.get_by_role('checkbox', name='Выбрать всю группу: Цены', exact=True)).to_have_count(0)
        dialog.get_by_role('checkbox', name='ЦенаРозничная', exact=True).check()
        expect(dialog.get_by_role('checkbox', name='ЦенаОптовая', exact=True)).not_to_be_checked()
        for label in ('Формировать по категориям', 'Формировать по группам', 'Форма для заказа', 'По всем категориям (zip)'):
            dialog.get_by_role('checkbox', name=label, exact=True).check()
        dialog.locator('.MuiDialogContent-root').evaluate('(node) => node.scrollTop = 0')
        page.screenshot(path=str(artifacts / f'excel-forms-{width}.png'))
        expect(dialog.get_by_text('Выбрано колонок: 7', exact=True)).to_be_visible()
        dialog.get_by_role('button', name='Скачать ZIP', exact=True).click()
        expect(dialog.get_by_role('checkbox', name='Форма для заказа', exact=True)).to_be_disabled()
        expect(dialog.get_by_role('alert')).to_have_text('Тестовая ошибка экспорта', timeout=10000)
        payload = parse_qs(urlsplit(exports[-1]).query)
        assert [column for column in payload['column'] if column.startswith('price:')] == ['price:ЦенаРозничная']
        assert all(payload[key] == ['true'] for key in ('group_categories', 'group_folders', 'promotion', 'order_form', 'zip_categories'))
        dialog.get_by_role('button', name='Снять все', exact=True).click()
        expect(dialog.get_by_role('button', name='Скачать ZIP', exact=True)).to_be_disabled()
        dialog.get_by_role('button', name='Стандартный набор', exact=True).click()
        expect(dialog.get_by_role('checkbox', name='Форма для заказа', exact=True)).not_to_be_checked()
        expect(dialog.get_by_role('button', name='Скачать Excel', exact=True)).to_be_enabled()
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        assert not errors, errors
        context.close()
    browser.close()
print('Desktop/mobile Excel dialog: fullscreen, groups, links, defaults, disabled-empty/busy, export payload, error and Escape passed')
