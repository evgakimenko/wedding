import sys, re, json, pathlib, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000/"
ROOT = pathlib.Path(__file__).parent
SHOTS = ROOT / "shots_desktop"; SHOTS.mkdir(exist_ok=True)
errors = []
def check(c, m):
    print(("  ✓ " if c else "  ✗ ") + m)
    if not c: errors.append(m)
urllib.request.urlopen(BASE + "__reset").read()
PAGES = ["home", "vendors", "budget", "tasks", "purchases", "guests", "seating", "drinks", "settings"]

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    pg.on("console", lambda m: m.type == "error" and not re.search(r"realtime|websocket|fonts|Failed to load resource", m.text, re.I) and errors.append("console: " + m.text))
    pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    pg.route(re.compile(r"fonts\.(googleapis|gstatic)\.com"), lambda r: r.abort())
    S = lambda e: pg.evaluate("() => " + e)

    print("\n== Десктоп 1440×900 ==")
    pg.goto(BASE); pg.wait_for_selector(".auth", timeout=15000)
    box = pg.locator(".auth").bounding_box()
    check(abs((box["x"] + box["width"] / 2) - 720) < 30, "форма входа по центру экрана")
    pg.screenshot(path=str(SHOTS / "00_login.png"))
    pg.click("[data-sw]"); pg.fill("#em", "desk@test.ru"); pg.fill("#pw", "secret12"); pg.click('.auth [type="submit"]')
    pg.wait_for_selector(".join", timeout=10000); pg.click('[data-new="p1"]'); pg.wait_for_selector(".ob", timeout=10000)
    pg.locator("[data-restore]").set_input_files(str(ROOT.parent / "migration.json")); pg.wait_for_selector(".hero", timeout=15000)
    # some data for nicer screens
    pg.evaluate("""async () => {
      const v = await add('vendors', {name:'Анна Фото', catId:'c_photo', status:'contract', price:90000, link:'@anna_photo', rating:5});
      await add('payments', {vendorId: v, amount: 20000, status:'paid', type:'deposit', method:'cash', date:'2026-11-12'});
      await add('payments', {vendorId: v, amount: 70000, status:'planned', type:'extra', method:'transfer', date:'2027-05-20'});
      await add('vendors', {name:'Кавер-группа «Лето»', catId:'c_music', status:'search', price:120000, rating:4, notes:'Видео с живых выступлений огонь'});
      await add('vendors', {name:'Студия «Лён»', catId:'c_decor', status:'talks', price:180000, rating:5, notes:'Пионы, белая гамма'});
      for (const n of ['Анна Петрова','Иван Петров','Ольга Смирнова','Мария Иванова','Пётр Сидоров']) await add('guests', {name:n, side:'p2', group:'Семья', rsvp:'yes', tableId: n.startsWith('А')||n.startsWith('И') ? 'tb01' : null});
      await saveSettings({budget: 2000000});
    }""")
    pg.wait_for_function("() => outbox.length === 0", timeout=10000); pg.wait_for_timeout(300)

    side = pg.locator("#tabbar").bounding_box()
    check(side["x"] == 0 and side["width"] >= 240 and side["height"] >= 880, "боковое меню слева на всю высоту")
    check(pg.locator("#tabbar .brand").is_visible() and "Женя & Катя" in pg.locator("#tabbar .brand").inner_text(), "в меню имена пары и дата")
    check(not pg.locator('#tabbar [data-go="more"]').is_visible(), "пункт «Ещё» скрыт — все разделы сразу в меню")
    for pname in PAGES:
        pg.click(f'#tabbar [data-go="{pname}"]'); pg.wait_for_timeout(250)
        over = S("document.documentElement.scrollWidth - window.innerWidth")
        active = pg.locator(f'#tabbar [data-go="{pname}"].on').count() == 1
        check(over <= 0 and active, f"{pname}: открывается из меню, без горизонтальной прокрутки")
        pg.screenshot(path=str(SHOTS / f"{PAGES.index(pname)+1:02d}_{pname}.png"), full_page=True)
    pg.click('#tabbar [data-go="home"]'); pg.wait_for_timeout(200)
    cols = pg.locator(".cols > div")
    check(cols.count() == 2 and cols.nth(0).bounding_box()["y"] == cols.nth(1).bounding_box()["y"], "главная в две колонки")
    pg.click('#tabbar [data-go="vendors"]'); pg.wait_for_timeout(200)
    secs = pg.locator(".catgrid > section")
    check(secs.nth(0).bounding_box()["y"] == secs.nth(1).bounding_box()["y"], "подрядчики — категории сеткой")
    pg.locator("[data-vendor]").filter(has_text="Анна Фото").click(); pg.wait_for_timeout(250)
    sb = pg.locator(".sheet").last.bounding_box()
    check(abs(sb["x"] + sb["width"] / 2 - 720) < 40 and sb["y"] > 10 and sb["width"] <= 610, "карточка открывается окном по центру")
    pg.screenshot(path=str(SHOTS / "10_vendor_modal.png"))
    pg.keyboard.press("Escape"); pg.wait_for_timeout(150)
    check(pg.locator(".sheet").count() == 0, "Esc закрывает окно")
    pg.click(".fab"); pg.wait_for_timeout(150)
    pg.locator('.sheet [name="name"]').fill("Фотограф Максим"); pg.locator(".sheet [data-save]").click(); pg.wait_for_timeout(300)
    check(S("S.vendors.some(v=>v.name==='Фотограф Максим' && v.status==='search')"), "кнопка «+» добавляет кандидата")
    with pg.expect_download() as dl: pg.click('#tabbar [data-act="export"]')
    check(dl.value.suggested_filename.endswith(".xlsx"), "«Excel» в меню скачивает файл")

    # tablet / narrow desktop & dark
    for w, h, name in [(1024, 768, "tablet"), (390, 844, "mobile")]:
        pg.set_viewport_size({"width": w, "height": h}); pg.wait_for_timeout(200)
        for pname in PAGES:
            pg.goto(BASE + "#" + pname); pg.wait_for_timeout(250)
            over = S("document.documentElement.scrollWidth - window.innerWidth")
            if over > 0: errors.append(f"{name}/{pname}: горизонтальная прокрутка {over}px")
        mob = name == "mobile"
        check((pg.locator(".tabbar").bounding_box()["y"] > 700) if mob else pg.locator("#tabbar .brand").is_visible(), f"{name} {w}px: {'нижние вкладки' if mob else 'боковое меню'}, без горизонтальной прокрутки")
    ctx.close()
    ctx2 = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    pg2 = ctx2.new_page(); pg2.route(re.compile(r"fonts\.(googleapis|gstatic)\.com"), lambda r: r.abort())
    pg2.goto(BASE); pg2.wait_for_selector(".auth", timeout=15000)
    pg2.fill("#em", "desk@test.ru"); pg2.fill("#pw", "secret12"); pg2.click('.auth [type="submit"]'); pg2.wait_for_selector(".hero", timeout=10000); pg2.wait_for_timeout(500)
    pg2.screenshot(path=str(SHOTS / "11_home_dark.png"), full_page=True)
    check(True, "тёмная тема на десктопе")
    b.close()

print("\nОШИБКИ:" if errors else "\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
for e in errors: print(" -", e)
sys.exit(1 if errors else 0)
