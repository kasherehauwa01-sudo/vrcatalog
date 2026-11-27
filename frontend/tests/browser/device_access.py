"""Run against local Vite: PKCS12_UI_URL=http://localhost:5176/vr/catalog/ python this_file.
Requires optional Playwright and Chromium; all API responses are synthetic.
"""
import os
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get('PKCS12_UI_URL', 'http://localhost:5176/vr/catalog/')
PASSWORD = 'Ab9' * 10 + 'Z1'
HTML = '''<html><body><div id="root"></div><script type="module">
import RefreshRuntime from '/vr/catalog/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type;
window.__vite_plugin_react_preamble_installed__=true;
const {default: React} = await import('/vr/catalog/node_modules/.vite/deps/react.js');
const {default: {createRoot}} = await import('/vr/catalog/node_modules/.vite/deps/react-dom_client.js');
const {DeviceAccess} = await import('/vr/catalog/src/components/DeviceAccess.tsx');
createRoot(document.getElementById('root')).render(React.createElement(DeviceAccess));
</script></body></html>'''

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM', '/usr/bin/chromium'), args=['--no-sandbox'])
    page = browser.new_page()
    page.on("pageerror", lambda error: print(str(error), flush=True))
    posts = []
    def respond(route):
        req = route.request
        if req.url.endswith('/admin/session'):
            route.fulfill(json={'authenticated': True, 'csrf_token': 'test'})
        elif req.method == 'GET':
            route.fulfill(json=[])
        else:
            posts.append(req.post_data_json)
            route.fulfill(status=201, json={'device': {'id': 1, 'name': 'Test device'}, 'password': PASSWORD,
                'filename': 'device-abc.p12', 'pkcs12_base64': 'AQID'})
    page.route('**/vr/catalog/api/**', respond)
    page.route('**/device-ui-test', lambda route: route.fulfill(content_type='text/html', body=HTML))
    page.goto(URL + 'device-ui-test')
    page.get_by_role('button', name='Выпустить сертификат', exact=True).click()
    form = page.get_by_role('dialog')
    submit = form.get_by_role('button', name='Выпустить сертификат', exact=True)
    expect(submit).to_be_disabled()
    assert form.locator('input[type=password]').count() == 0
    form.get_by_label('Устройство', exact=False).fill('Test device')
    form.get_by_label('Владелец', exact=False).fill('Owner')
    submit.click()
    secret = page.get_by_label('Пароль PKCS12')
    expect(secret).to_have_attribute('type', 'password')
    page.get_by_role('button', name='Показать пароль').click()
    expect(secret).to_have_value(PASSWORD)
    page.get_by_role('button', name='Скрыть пароль').click()
    expect(secret).to_have_attribute('type', 'password')
    page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied')}}})")
    page.get_by_role('button', name='Скопировать пароль').click()
    expect(page.get_by_text('Не удалось скопировать пароль.', exact=False)).to_be_visible()
    page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{}}})")
    page.get_by_role('button', name='Скопировать пароль').click()
    expect(page.get_by_role('button', name='Скопировано')).to_be_visible()
    page.evaluate("() => { window.savedCreateObjectURL = URL.createObjectURL; URL.createObjectURL = () => {throw Error('download blocked')}; }")
    page.get_by_role('button', name='Скачать сертификат (.p12)').click()
    expect(page.get_by_text('Не удалось начать скачивание.', exact=False)).to_be_visible()
    page.evaluate("URL.createObjectURL = window.savedCreateObjectURL; delete window.savedCreateObjectURL")
    with page.expect_download() as downloaded:
        page.get_by_role('button', name='Скачать сертификат (.p12)').click()
    assert downloaded.value.suggested_filename == 'device-abc.p12'
    expect(secret).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.get_by_text('Вы сохранили сертификат и пароль?', exact=False)).to_be_visible()
    page.get_by_role('button', name='Вернуться').click()
    page.locator('.MuiDialog-container').last.click(position={'x': 5, 'y': 5})
    expect(page.get_by_text('Вы сохранили сертификат и пароль?', exact=False)).to_be_visible()
    page.get_by_role('button', name='Вернуться').click()
    page.get_by_role('button', name='Готово', exact=True).click()
    page.get_by_role('button', name='Да, закрыть').click()
    expect(secret).to_have_count(0)
    assert len(posts) == 1 and 'password' not in posts[0]
    assert page.evaluate('JSON.stringify([localStorage,sessionStorage])').find(PASSWORD) == -1
    page.get_by_role('button', name='Выпустить сертификат', exact=True).click()
    assert page.locator('input[type=password]').count() == 0
    browser.close()
print('Device access browser checks passed')
