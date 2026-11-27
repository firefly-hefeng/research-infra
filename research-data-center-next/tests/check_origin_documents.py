"""Browser regression for the origin-document reader. Feishu responses are fixtures."""
import json
from datetime import date
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from catalog import import_catalog
from server import create_server
from test_catalog import sample_document


def verify(browser, base, width, items):
    context = browser.new_context(viewport={"width": width, "height": 900},
                                  is_mobile=width <= 800, has_touch=width <= 800)
    state = {"text": "源版本一", "denied": False}
    context.route("**/progress/**", lambda route: route.abort())

    def source(route):
        # The provider decides whether this reader may see the source.
        route.fulfill(status=403 if state["denied"] else 200, content_type="text/html; charset=utf-8",
                      body=f"<h1>{'请在飞书申请访问权限' if state['denied'] else state['text']}</h1>")

    context.route("https://wcn5kauqqbj1.feishu.cn/**", source)
    page = context.new_page()
    page.goto(base + "/#documents/research-wiki")
    expect(page.locator("#documents-title")).to_have_text("原点文档")
    article, frame = page.locator(".document-reading"), page.frame_locator(".document-live iframe")
    expect(frame.get_by_role("heading")).to_have_text("源版本一")
    expect(article.get_by_role("link", name="在飞书打开原件")).to_have_attribute("rel", "noopener noreferrer")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
    if width <= 800:
        menu = page.get_by_role("combobox", name="选择原点文档")
        expect(menu).to_be_visible()
        assert menu.locator("option").count() == len(items)
        menu.select_option("agent-handbook")
    else:
        page.locator('.document-index a[href="#documents/agent-handbook"]').click()
    expect(article.get_by_role("heading", level=2)).to_have_text("Agent 协作与接入指南")
    assert page.locator(".document-live iframe").count() == 0
    article.get_by_text("阅读平台原文", exact=True).click()
    expect(article.locator("pre")).to_have_attribute("data-state", "ready")
    assert article.locator("pre").text_content() == (ROOT / "docs/agent-guide.md").read_text(encoding="utf-8")
    state["text"] = "源版本二"
    page.go_back()
    expect(frame.get_by_role("heading")).to_have_text("源版本二")
    state["denied"] = True
    page.reload()
    expect(frame.get_by_role("heading")).to_have_text("请在飞书申请访问权限")
    assert "源版本二" not in article.text_content()
    long_id = "speech-state-context"
    page.evaluate("(id) => location.hash = '#documents/' + id", long_id)
    expect(article.get_by_role("heading", level=2)).to_contain_text("语音特质")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
    page.evaluate("location.hash = '#documents/nonexistent'")
    expect(page.locator("#documents-status")).to_contain_text("未找到")
    assert page.locator(".document-live iframe").count() == 0

    for item in items:
        if item.get("source_mode") != "feishu_window":
            continue
        page.evaluate("(id) => location.hash = '#documents/' + id", item["id"])
        expect(article.get_by_role("heading", level=2)).to_have_text(item["title"])
        original = article.get_by_role("link", name="查看原文")
        expect(original).to_have_attribute("href", item["url"])
        expect(original).to_have_attribute("target", "_blank")
        expect(original).to_have_attribute("rel", "noopener noreferrer")
        expect(page.locator(".document-live iframe")).to_have_count(0)

    invalid = {"id": "wrong-host", "title": "其他来源", "source_mode": "feishu_live",
               "url": "https://example.invalid/wiki/untrusted", "summary": ""}
    context.route("**/api/workspace-docs", lambda r: r.fulfill(json={"items": [invalid]}))
    page.goto(base + "/#documents/wrong-host")
    page.reload()
    expect(article.get_by_role("heading", level=2)).to_have_text("其他来源")
    assert page.locator(".document-live iframe").count() == 0
    context.close()


def main():
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "catalog.sqlite3"
        import_catalog(sample_document(), db)
        http = create_server(db, port=0)
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{http.server_port}"
            with urlopen(base + "/api/workspace-docs") as response:
                items = json.load(response)["items"]
                assert "frame-src" not in response.headers["Content-Security-Policy"]
            with urlopen(base + "/") as response:
                policy = response.headers["Content-Security-Policy"]
            assert "frame-src 'self' https://wcn5kauqqbj1.feishu.cn;" in policy
            assert "frame-ancestors 'none'" in policy
            assert len(items) == len({item["id"] for item in items})
            assert all("body" not in item and "markdown" not in item for item in items)
            for item in items:
                if item["id"].startswith("seminar-"):
                    day = date.fromisoformat(item["id"].removeprefix("seminar-"))
                    year, week, _ = day.isocalendar()
                    urls = {link["url"] for section in item["sections"] for link in section.get("links", [])}
                    assert f"/progress/#team?week={year}-W{week:02}" in urls
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch()
                for width in (1440, 390, 320):
                    verify(browser, base, width, items)
                    print(f"PASS {width}px")
                browser.close()
        finally:
            http.shutdown()
            http.server_close()
            thread.join()


if __name__ == "__main__":
    main()
