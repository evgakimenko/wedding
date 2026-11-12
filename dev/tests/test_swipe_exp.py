import sys, re, pathlib, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000/"
ROOT = pathlib.Path(__file__).parent
SHOTS = ROOT / "shots_exp"; SHOTS.mkdir(exist_ok=True)
errors = []
def check(c, m):
    print(("  ✓ " if c else "  ✗ ") + m)
    if not c: errors.append(m)
urllib.request.urlopen(BASE + "__reset").read()

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, accept_downloads=True)
    pg = ctx.new_page()
    pg.on("console", lambda m: m.type == "error" and not re.search(r"realtime|websocket|fonts|Failed to load resource", m.text, re.I) and errors.append("console: " + m.text))
    pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    pg.route(re.compile(r"fonts\.(googleapis|gstatic)\.com"), lambda r: r.abort())
    S = lambda e: pg.evaluate("() => " + e)
    sheet = lambda: pg.locator(".sheet").last
    def synced(): pg.wait_for_function("() => outbox.length === 0", timeout=10000)

    def swipe_left(loc, dist=150):
        loc.scroll_into_view_if_needed()
        bb = loc.bounding_box(); y = bb["y"] + bb["height"] / 2; x = bb["x"] + bb["width"] - 30
        pg.mouse.move(x, y); pg.mouse.down()
        for i in range(1, 11): pg.mouse.move(x - dist * i / 10, y + 2)
        pg.mouse.up(); pg.wait_for_timeout(300)
    def swipe_delete(kind, id_):
        sw = pg.locator(f'.sw[data-sw="{kind}:{id_}"]')
        swipe_left(sw.locator(".swc"))
        ok = sw.evaluate("e => e.classList.contains('open')")
        sw.locator("[data-swdel]").click(); pg.wait_for_timeout(150)
        pg.locator(".modal [data-y]").click(); pg.wait_for_timeout(300)
        return ok

    pg.goto(BASE); pg.wait_for_selector(".auth", timeout=15000)
    pg.click("[data-sw]"); pg.fill("#em", "exp@test.ru"); pg.fill("#pw", "secret12"); pg.click('.auth [type="submit"]')
    pg.wait_for_selector(".join", timeout=10000); pg.click('[data-new="p1"]'); pg.wait_for_selector(".ob", timeout=10000)
    pg.locator("[data-restore]").set_input_files(str(ROOT.parent / "migration.json")); pg.wait_for_selector(".hero", timeout=15000)

    print("\n== Расходы ==")
    pg.click('[data-go="budget"]'); pg.wait_for_timeout(200)
    check(pg.locator(".fab").is_visible(), "на экране бюджета есть «+» внизу справа")
    pg.click(".fab"); pg.wait_for_selector(".expf"); pg.wait_for_timeout(450)
    check(pg.evaluate("() => document.activeElement && document.activeElement.name") == "amount", "поле суммы сразу в фокусе")
    pg.locator('.expf [name="amount"]').fill("15 000")
    pg.locator('.expf [data-ec="c_bride"]').click()
    pg.locator('.expf [name="title"]').fill("Пробный макияж")
    pg.locator('.expf [data-payer="p2"]').click()
    pg.locator(".expf [data-rfile]").set_input_files(str(ROOT / "receipt_test.jpg")); pg.wait_for_selector(".rprev img", timeout=5000)
    pg.screenshot(path=str(SHOTS / "01_expense_form.png"))
    pg.locator(".expf [data-save]").click(); pg.wait_for_timeout(600); synced()
    x = S("S.expenses[0]")
    check(x and x["amount"] == 15000 and x["catId"] == "c_bride" and x["payer"] == "p2" and x["hasReceipt"] is True and x["title"] == "Пробный макияж", "расход сохранён: сумма, категория, кто платил, чек")
    img = pg.evaluate("async () => { const r = await sb.from('docs').select('data').eq('wedding_id', W).eq('coll','receipts').eq('id', S.expenses[0].id); return r.data[0] && r.data[0].data.img.slice(0, 23); }")
    check(img == "data:image/jpeg;base64,", "фото чека сжато и сохранено на сервере")
    check(S("S.receipts === undefined && !JSON.stringify(S).includes('base64')"), "чеки не грузятся в общий список (быстро и экономно)")
    T = S("totals()"); bs = S("catStats(catById('c_bride'))")
    check(T["paid"] == 15000 and bs["contract"] == 15000, "расход учтён в бюджете и в категории «Образ невесты»")
    check("Пробный макияж" in pg.locator("#app").inner_text() and "🧾" in pg.locator("#app").inner_text(), "расход в списке с иконкой чека")
    pg.screenshot(path=str(SHOTS / "02_budget_with_expense.png"), full_page=True)
    pg.locator("[data-exp]").first.click(); pg.wait_for_selector(".rprev img", timeout=5000)
    check(pg.locator(".rprev img").get_attribute("src").startswith("data:image/jpeg"), "чек открывается при просмотре расхода")
    pg.locator('.expf [name="amount"]').fill("16000"); pg.locator(".expf [data-save]").click(); pg.wait_for_timeout(300)
    check(S("S.expenses[0].amount") == 16000 and S("S.expenses[0].hasReceipt") is True, "редактирование суммы, чек сохранился")
    pg.locator('.row[data-cat="c_bride"]').click(); pg.wait_for_timeout(200)
    check("Пробный макияж" in sheet().inner_text(), "тап по категории показывает её расходы")
    sheet().locator("[data-addexp]").click(); pg.wait_for_selector(".expf")
    check(pg.locator('.expf [data-ec="c_bride"].on').count() == 1, "«Расход в эту категорию» — категория выбрана заранее")
    pg.locator('.expf [name="amount"]').fill("3500"); pg.locator('.expf [name="title"]').fill("Фата"); pg.locator(".expf [data-save]").click(); pg.wait_for_timeout(300)
    pg.click(".fab"); pg.locator('.expf [data-save]').click(); pg.wait_for_timeout(200)
    check(pg.locator(".expf").count() == 1 and S("S.expenses.length") == 2, "без суммы расход не сохраняется")
    pg.keyboard.press("Escape")
    synced()

    print("\n== Свайп «Удалить» ==")
    eid = S("S.expenses.find(e=>e.title==='Пробный макияж').id")
    opened = swipe_delete("expenses", eid)
    check(opened, "свайп влево открывает кнопку «Удалить»")
    check(not S(f"S.expenses.some(e=>e.id==='{eid}')"), "расход удалён свайпом")
    synced(); pg.wait_for_timeout(300)
    left = pg.evaluate(f"async () => (await sb.from('docs').select('id').eq('wedding_id', W).eq('coll','receipts').eq('id','{eid}')).data.length")
    check(left == 0, "фото чека удалено вместе с расходом")
    # short horizontal jitter must not open nor block click
    row = pg.locator(".sw[data-sw^='categories:'] .swc").first
    row.scroll_into_view_if_needed(); pg.wait_for_timeout(100)
    bb = row.bounding_box(); pg.mouse.click(bb["x"] + 100, bb["y"] + bb["height"] / 2); pg.wait_for_timeout(200)
    check(pg.locator(".sheet").count() == 1, "обычный тап по строке по-прежнему открывает её")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(100)
    # categories
    check(pg.locator(".addrow[data-act='category']").is_visible() and pg.locator(".addrow[data-act='category']").bounding_box()["height"] >= 48, "крупная кнопка «＋ Добавить категорию»")
    pg.click(".addrow[data-act='category']"); pg.locator('.sheet [name="name"]').fill("Путешествие"); pg.locator(".sheet [data-save]").click(); pg.wait_for_timeout(300)
    trip = S("S.categories.find(c=>c.name==='Путешествие').id")
    pg.click(".fab"); pg.locator('.expf [name="amount"]').fill("50000"); pg.locator(f'.expf [data-ec="{trip}"]').click(); pg.locator('.expf [name="title"]').fill("Билеты"); pg.locator(".expf [data-save]").click(); pg.wait_for_timeout(300)
    swipe_delete("categories", trip)
    check(not S(f"S.categories.some(c=>c.id==='{trip}')"), "категория удалена свайпом")
    check(S("S.expenses.find(e=>e.title==='Билеты').catId") == "c_other", "её расходы переехали в «Прочее»")
    T = S("totals()"); check(T["paid"] == 53500, f"бюджет пересчитан ({T['paid']})")
    # vendors
    pg.click('[data-go="vendors"]'); pg.wait_for_timeout(200)
    pg.screenshot(path=str(SHOTS / "03_vendors.png"))
    opened = swipe_delete("vendors", "v_soma")
    check(opened and not S("S.vendors.some(v=>v.id==='v_soma')"), "подрядчик удалён свайпом")
    # tasks / purchases / guests
    pg.click('[data-go="tasks"]'); pg.wait_for_timeout(200); pg.click('[data-tf="all"]'); pg.wait_for_timeout(100)
    tid = pg.locator(".sw[data-sw^='tasks:']").first.get_attribute("data-sw").split(":")[1]
    swipe_delete("tasks", tid); check(not S(f"S.tasks.some(t=>t.id==='{tid}')"), "задача удалена свайпом")
    pg.goto(BASE + "#purchases"); pg.wait_for_timeout(400)
    pid = pg.locator(".sw[data-sw^='purchases:']").first.get_attribute("data-sw").split(":")[1]
    swipe_delete("purchases", pid); check(not S(f"S.purchases.some(t=>t.id==='{pid}')"), "покупка удалена свайпом")
    pg.goto(BASE + "#guests"); pg.wait_for_timeout(400)
    pg.click('[data-act="bulkGuests"]'); sheet().locator('[name="names"]').fill("Анна\nИван"); sheet().locator("[data-save]").click(); pg.wait_for_timeout(300)
    gid = pg.locator(".sw[data-sw^='guests:']").first.get_attribute("data-sw").split(":")[1]
    swipe_delete("guests", gid); check(S("S.guests.length") == 1, "гость удалён свайпом")
    pg.locator("#gq").fill("иван"); pg.wait_for_timeout(100)
    check(pg.locator("#glist .sw:visible").count() == 1, "поиск гостей работает со свайп-строками")
    synced()
    # cancel swipe-delete keeps item
    pg.goto(BASE + "#budget"); pg.wait_for_timeout(400)
    cid = "c_cake"; sw = pg.locator(f'.sw[data-sw="categories:{cid}"]'); swipe_left(sw.locator(".swc")); sw.locator("[data-swdel]").click(); pg.locator(".modal [data-n]").click(); pg.wait_for_timeout(200)
    check(S(f"!!catById('{cid}')"), "«Отмена» в подтверждении ничего не удаляет")
    with pg.expect_download() as dl: pg.click('[data-act="export"]')
    import openpyxl, io
    wb = openpyxl.load_workbook(io.BytesIO(pathlib.Path(dl.value.path()).read_bytes()))
    check("Расходы" in wb.sheetnames and any(r[1] == "Билеты" for r in wb["Расходы"].iter_rows(values_only=True)), "расходы попадают в Excel")
    # desktop expense modal
    pg.set_viewport_size({"width": 1440, "height": 900}); pg.wait_for_timeout(200)
    pg.click(".fab"); pg.wait_for_selector(".expf"); pg.screenshot(path=str(SHOTS / "04_desktop_expense.png"))
    bb = pg.locator(".sheet").last.bounding_box(); check(abs(bb["x"] + bb["width"] / 2 - 720) < 40, "на десктопе форма расхода по центру")
    b.close()

print("\nОШИБКИ:" if errors else "\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
for e in errors: print(" -", e)
sys.exit(1 if errors else 0)
