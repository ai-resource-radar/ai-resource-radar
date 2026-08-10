"""Static contracts for the dependency-free modular browser surfaces."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1] / "src/ai_resource_radar"
LOCAL = ROOT / "web"
PUBLIC = ROOT / "public_web"


class FrontendContractTests(unittest.TestCase):
    def test_local_dashboard_has_single_grouped_nav_and_progressive_disclosures(self) -> None:
        html = (LOCAL / "index.html").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('id="main-content"', html)
        self.assertIn('aria-label="主要功能"', html)
        for label in ("免费资源", "价格榜单", "日报", "技巧"):
            self.assertIn(label, html)
        self.assertNotIn('class="nav-more"', html)
        self.assertNotIn('data-view="changes"', html)
        self.assertIn('data-open-view="changes"', html)
        self.assertIn('id="view-subnav"', html)
        self.assertIn('id="free-quick-filters"', html)
        self.assertNotIn("catalog-view-chips", html)
        self.assertIn('id="pricing-advanced"', html)
        self.assertIn('id="toggle-price-filters"', html)
        local_javascript = "\n".join(path.read_text(encoding="utf-8") for path in LOCAL.rglob("*.js"))
        self.assertIn('"poster-diagnostics"', local_javascript)
        self.assertIn('class="source-health-disclosure"', html)
        self.assertEqual(len(set(re.findall(r'data-view="([^"]+)"', html))), 8)

    def test_local_entry_uses_cancellable_native_module_and_url_state(self) -> None:
        javascript = (LOCAL / "ai-resources.js").read_text(encoding="utf-8")
        module = "\n".join(path.read_text(encoding="utf-8") for path in (LOCAL / "modules").rglob("*.js"))
        self.assertIn('from "/ai-radar-assets/modules/legacy-dashboard.js"', javascript)
        self.assertIn('from "/ai-radar-assets/modules/api.js"', module)
        self.assertIn("requestJson", javascript + module)
        self.assertIn("AbortController", javascript + module)
        self.assertIn("readDashboardRoute", javascript + module)
        self.assertIn("writeDashboardRoute", javascript + module)
        self.assertIn('window.addEventListener("hashchange", restoreRoute)', module)
        self.assertIn('window.addEventListener("popstate", restoreRoute)', module)
        self.assertIn('registry.resources?.loadResources?.(ctx)', module)
        self.assertIn("FILTER_KEYS", module)
        for route_filter in ("verified", "mainland", "provider", "tip_status"):
            self.assertIn(f'"{route_filter}"', module)
        self.assertIn("createDialogController", javascript + module)
        self.assertIn("PRICE_PAGE_SIZE = 20", module)
        self.assertIn("appendPricePager", module)
        self.assertIn('setAttribute("role", "button")', module)
        self.assertIn('setAttribute("aria-haspopup", "dialog")', module)
        self.assertLess(len(javascript.splitlines()), 500)
        for layer in ("tokens", "base", "layout", "components", "views", "responsive"):
            self.assertTrue((LOCAL / "styles" / f"{layer}.css").exists())
        self.assertLess(len((LOCAL / "styles" / "legacy.css").read_text(encoding="utf-8").splitlines()), 40)
        styles = "\n".join((LOCAL / "styles" / name).read_text(encoding="utf-8") for name in ("components.css", "views.css"))
        for selector in (".feature-card:focus-visible", ".tip-card:focus-visible"):
            self.assertIn(selector, styles)
        for selector in (".feature-claim", ".feature-details", ".provider-claim", ".provider-details"):
            self.assertIn(selector, styles)
        self.assertIn("var(--radar-focus-ring)", styles)

    def test_bilingual_public_site_keeps_static_module_and_shared_tokens(self) -> None:
        html = (PUBLIC / "index.html").read_text(encoding="utf-8")
        javascript = (PUBLIC / "app.js").read_text(encoding="utf-8")
        styles = (PUBLIC / "styles.css").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('Content-Security-Policy', html)
        self.assertIn('role="tablist"', html)
        self.assertIn('role="tabpanel"', html)
        self.assertIn('from "./ui-modules.js"', javascript)
        self.assertIn('"ArrowRight"', javascript)
        self.assertIn('document.title = state.locale', javascript)
        self.assertIn('@import url("./radar-tokens.css")', styles)
        self.assertTrue((PUBLIC / "radar-tokens.css").exists())
        self.assertNotIn("innerHTML", javascript)


if __name__ == "__main__":
    unittest.main()
