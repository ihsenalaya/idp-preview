"""
Browser E2E tests using Playwright — validates the real user experience.
Tests run headless Chromium against the live preview app deployed by Cellenza.
Output lines starting with PASS/FAIL are parsed by the Cellenza operator.
"""
import os
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE = os.environ.get("APP_URL", "http://app:80")

passed = 0
failed = 0


def run(name, fn):
    global passed, failed
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page()
        try:
            fn(page)
            print(f"PASS e2e {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL e2e {name}: {e}")
            failed += 1
        except PlaywrightTimeout as e:
            print(f"FAIL e2e {name}: timeout — {e}")
            failed += 1
        except Exception as e:
            print(f"FAIL e2e {name}: {e}")
            failed += 1
        finally:
            browser.close()


def test_catalog_page_loads(page):
    """Page renders the product grid with at least one card."""
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    grid = page.locator('[data-testid="product-grid"]')
    grid.wait_for(state="visible", timeout=10000)
    cards = page.locator('[data-testid="product-card"]')
    count = cards.count()
    assert count > 0, f"expected at least 1 product card, got {count}"


def test_preview_badge_shown(page):
    """Preview banner shows PR number and branch when PREVIEW_PR env is set."""
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    badge = page.locator('[data-testid="preview-badge"]')
    if badge.count() == 0:
        # PREVIEW_PR not set in this environment — skip gracefully
        return
    badge.wait_for(state="visible", timeout=5000)
    text = badge.inner_text()
    assert "PR" in text, f"preview banner missing PR reference, got: {text!r}"


def test_product_detail_panel(page):
    """Click a product card opens the detail side panel with name and price."""
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    cards = page.locator('[data-testid="product-card"]')
    cards.first.wait_for(state="visible", timeout=10000)
    cards.first.click()

    detail = page.locator('[data-testid="product-detail"]')
    detail.wait_for(state="visible", timeout=10000)

    name_el = page.locator('[data-testid="detail-name"]')
    name_el.wait_for(state="visible", timeout=8000)
    assert name_el.inner_text().strip() != "", "detail-name is empty"

    price_el = page.locator('[data-testid="detail-price"]')
    price_el.wait_for(state="visible", timeout=8000)
    assert "€" in price_el.inner_text(), "detail-price missing € symbol"


def test_related_section(page):
    """Product detail panel includes a related-products section."""
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    page.locator('[data-testid="product-card"]').first.wait_for(state="visible", timeout=10000)
    page.locator('[data-testid="product-card"]').first.click()

    related = page.locator('[data-testid="related-section"]')
    related.wait_for(state="visible", timeout=10000)
    assert related.is_visible(), "related-section not visible in product detail panel"


def test_discount_filter(page):
    """Discount filter re-renders the grid with only matching products."""
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    page.locator('[data-testid="product-grid"]').wait_for(state="visible", timeout=10000)
    initial_count = page.locator('[data-testid="product-card"]').count()

    page.locator('[data-testid="discount-input"]').fill("50")
    page.locator('[data-testid="discount-apply"]').click()
    # Wait for JS fetch + DOM re-render
    page.wait_for_function("document.querySelectorAll('[data-testid=\"product-card\"]').length >= 0", timeout=8000)
    page.wait_for_timeout(600)

    filtered_count = page.locator('[data-testid="product-card"]').count()
    assert filtered_count <= initial_count, (
        f"filter returned {filtered_count} products, more than original {initial_count}"
    )
    if filtered_count > 0:
        badges = page.locator('[data-testid="product-discount"]').count()
        assert badges == filtered_count, (
            f"{filtered_count} filtered products but only {badges} have discount badges"
        )


def test_close_detail(page):
    """Close button hides the product detail overlay."""
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    page.locator('[data-testid="product-card"]').first.wait_for(state="visible", timeout=10000)
    page.locator('[data-testid="product-card"]').first.click()
    page.locator('[data-testid="product-detail"]').wait_for(state="visible", timeout=10000)

    page.locator('[data-testid="close-detail"]').click()
    page.wait_for_timeout(400)  # allow CSS transition
    overlay = page.locator('[data-testid="detail-overlay"]')
    assert not overlay.is_visible(), "detail overlay still visible after clicking close"


run("catalog_page_loads", test_catalog_page_loads)
run("preview_badge_shown", test_preview_badge_shown)
run("product_detail_panel", test_product_detail_panel)
run("related_section", test_related_section)
run("discount_filter", test_discount_filter)
run("close_detail", test_close_detail)

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
