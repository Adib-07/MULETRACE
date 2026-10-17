"""Render web/brand/logo.svg to PNG icons (32 px favicon, 180 px touch icon) with headless Chromium.
Dev-only dependency: pip install playwright && python -m playwright install chromium.  Run: python scripts/make_icons.py"""
from pathlib import Path
from playwright.sync_api import sync_playwright

svg = Path("web/brand/logo.svg").read_text()
with sync_playwright() as p:
    b = p.chromium.launch()
    for size in (32, 180):
        pg = b.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        pg.set_content(f'<html><body style="margin:0;background:transparent">{svg.replace("<svg ", f"<svg width=\"{size}\" height=\"{size}\" ", 1)}</body></html>')
        pg.screenshot(path=f"web/brand/icon-{size}.png", omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
        print("wrote", f"web/brand/icon-{size}.png")
    b.close()
