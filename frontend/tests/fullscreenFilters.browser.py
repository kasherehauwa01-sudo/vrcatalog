"""Run against local Vite with Python Playwright + Chromium; all API calls are mocked."""
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect

base = os.environ.get('CATALOG_TEST_URL', 'http://localhost:5173/vr/catalog/')
artifacts = Path(os.environ.get('CATALOG_TEST_ARTIFACTS', '/tmp/catalog-filter-previews'))
artifacts.mkdir(parents=True, exist_ok=True)
codes = ' '.join(f'CODE-{i:06d}' for i in range(300))
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    for width, height in ((1440, 1000), (390, 844)):
        context = browser.new_context(viewport={'width': width, 'height': height}, service_workers='block')
        page = context.new_page()
        searches = []
        filter_requests = []
        pending_brand = []
        errors = []
        page.on('pageerror', lambda error: (errors.append(str(error)), print(str(error), flush=True)))
        def api(route):
            url = urlsplit(route.request.url)
            path = url.path
            if '/api/filters' in path:
                filter_requests.append((path, parse_qs(url.query)))
            if path.endswith('/meta'):
                result = {'product_count': 300}
            elif path.endswith('/filters'):
                key = parse_qs(url.query)['filterKey'][0]
                if key == 'brand' and not pending_brand:
                    pending_brand.append(route)
                    return
                result = {'brand': ['Амфора']} if key == 'brand' else {'material': ['Стекло']}
            elif path.endswith('/filters/sections'):
                result = []
            elif path.endswith('/filters/folders'):
                result = ['МЕТАЛЛ|ПОСУДА для ПРИГОТОВЛЕНИЯ|АМФОРА (тандыры)']
            elif path.endswith('/products/search'):
                searches.append({'method': route.request.method, 'url': route.request.url, 'body': route.request.post_data})
                result = {'items': [], 'pagination': {'page': 1, 'pageSize': 100, 'totalItems': 0, 'totalPages': 0}}
            else:
                result = []
            route.fulfill(json=result)
        page.route('**/vr/catalog/api/**', api)
        page.goto(base)
        trigger = page.get_by_placeholder('Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам')
        trigger.click()
        dialog = page.get_by_role('dialog', name='Поиск и фильтры')
        expect(dialog).to_be_visible()
        entry = page.get_by_label('Код или список кодов', exact=True)
        expect(entry).to_be_focused()
        brand = dialog.get_by_role('button', name='Бренд', exact=True)
        expect(brand).to_be_visible()
        expect(dialog.get_by_role('button', name='Раздел', exact=True)).to_be_visible()
        expect(dialog.get_by_role('button', name='Коллекция', exact=True)).to_be_visible()
        assert filter_requests == []
        brand.click()
        expect(dialog.get_by_text('Загружаем значения…')).to_be_visible()
        assert [query['filterKey'] for _, query in filter_requests] == [['brand']]
        pending_brand[0].fulfill(status=503, json={})
        expect(dialog.get_by_role('alert')).to_have_text('Не удалось загрузить значения')
        dialog.get_by_role('button', name='Повторить').click()
        expect(dialog.get_by_role('button', name='Амфора')).to_be_visible()
        brand.click()
        brand.click()
        expect(dialog.get_by_role('button', name='Амфора')).to_be_visible()
        assert len(filter_requests) == 2
        dialog.get_by_role('button', name='Амфора').click()
        dialog.get_by_role('button', name='Подобрать по характеристикам').click()
        characteristics = page.get_by_role('dialog').filter(has=page.get_by_role('heading', name='Подобрать по характеристикам'))
        material = characteristics.get_by_role('button', name='Материал', exact=True)
        expect(material).to_be_visible()
        assert len(filter_requests) == 2
        material.click()
        expect(characteristics.get_by_role('button', name='Стекло')).to_be_visible()
        assert filter_requests[-1][1]['filterKey'] == ['material']
        assert filter_requests[-1][1]['brand'] == ['Амфора']
        characteristics.get_by_role('button', name='Готово').click()
        dialog.get_by_role('button', name='Раздел', exact=True).click()
        expect(dialog.get_by_label('Найти раздел...')).to_be_visible()
        assert filter_requests[-1][0].endswith('/filters/sections')
        dialog.get_by_role('button', name='Поиск по папке', exact=True).click()
        expect(dialog.get_by_text('МЕТАЛЛ', exact=True)).to_be_visible()
        assert filter_requests[-1][0].endswith('/filters/folders')
        assert len(filter_requests) == 5
        entry.focus()
        box = dialog.bounding_box()
        assert box['width'] == width and box['height'] == height, box
        entry = page.get_by_label('Код или список кодов', exact=True)
        expect(entry).to_be_focused()
        entry.fill(codes)
        entry.press('Enter')
        expect(dialog).to_be_visible()  # Enter adds a line, does not submit.
        expect(page.get_by_text('Кодов: 300 · уникальных: 300. Только точные совпадения.')).to_be_visible()
        page.wait_for_timeout(350)  # Finish the MUI dialog transition for the capture.
        assert dialog.evaluate('(node) => node.scrollWidth <= node.clientWidth')
        page.screenshot(path=str(artifacts / f'filters-{width}.png'))
        count = len(searches)
        page.get_by_role('button', name='Отмена', exact=True).click()
        expect(dialog).not_to_be_visible()
        assert len(searches) == count
        trigger.click()
        expect(entry).to_have_value('')
        entry.fill(codes)
        page.get_by_role('button', name='Показать товары', exact=True).click()
        page.wait_for_function("location.hash.includes('code=')")
        page.wait_for_timeout(500)
        assert searches[-1]['method'] == 'POST', searches[-1]
        assert json.loads(searches[-1]['body'])['code'] == codes
        assert 'code=' not in urlsplit(searches[-1]['url']).query
        expect(page.get_by_text('Код: 300 кодов', exact=True)).to_be_visible()
        page.reload()
        trigger.click()
        expect(entry).to_have_value(codes)
        page.get_by_role('button', name='Сбросить всё', exact=True).click()
        expect(entry).to_have_value('')
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        trigger.click()
        expect(entry).to_have_value(codes)  # Reset + cancel preserves applied filters.
        page.get_by_role('button', name='Сбросить всё', exact=True).click()
        page.get_by_role('button', name='Показать товары', exact=True).click()
        page.wait_for_function("!location.hash.includes('code=')")
        assert not errors, errors
        context.close()
    browser.close()
print('Desktop/mobile: lazy filter requests, loading, retry, caching, dependent characteristics, fullscreen, focus, 300-code paste, Enter, cancel, apply, POST, reload, reset and Escape passed')
