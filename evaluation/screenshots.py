"""Dev tool: capture screenshots of every page. Requires `pip install playwright && playwright install chromium`
and a running app (`streamlit run streamlit_app.py --server.port 8511`).

    python -m evaluation.screenshots [--base http://localhost:8511] [--out docs/screenshots]
"""

from __future__ import annotations

import argparse
from pathlib import Path

PAGES = ["overview", "visibility", "competitors", "perception", "sources", "recommendations", "monitoring", "settings"]


def main() -> None:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8511")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--mobile", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        sizes = [("desktop", 1440, 900)] + ([("mobile", 390, 844)] if args.mobile else [])
        for name, w, h in sizes:
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
            page = ctx.new_page()
            for slug in PAGES:
                page.goto(f"{args.base}/" + ("" if slug == "overview" else slug), wait_until="networkidle")
                page.wait_for_timeout(2500)
                page.screenshot(path=str(out / f"{slug}{'' if name == 'desktop' else '_' + name}.png"), full_page=True)
                print("captured", slug, name)
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
