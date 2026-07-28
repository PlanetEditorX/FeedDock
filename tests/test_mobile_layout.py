from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MobileLayoutTests(unittest.TestCase):
    def test_pages_opt_into_safe_area_viewport(self) -> None:
        for page in ("index.html", "login.html", "change-password.html"):
            html = (ROOT / "app/static" / page).read_text(encoding="utf-8")
            self.assertIn("viewport-fit=cover", html)

    def test_mobile_navigation_is_accessible_and_collapsible(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        module_path = ROOT / "app/static/navigation.js"
        self.assertIn('id="mobileNavToggle"', index)
        self.assertIn('aria-controls="primaryNavigation"', index)
        self.assertIn('id="primaryNavigation"', index)
        self.assertIn(".primary-nav.is-open", styles)
        self.assertIn("env(safe-area-inset-top)", styles)

        script = textwrap.dedent(
            f"""
            const assert = require('node:assert/strict');
            const navigation = require({str(module_path)!r});
            const classes = new Set();
            const bodyClasses = new Set();
            const attrs = {{}};
            const nav = {{ classList: {{
              toggle(name, enabled) {{ enabled ? classes.add(name) : classes.delete(name); }},
              contains(name) {{ return classes.has(name); }},
            }} }};
            const toggle = {{
              setAttribute(name, value) {{ attrs[name] = value; }},
            }};
            const doc = {{
              body: {{ classList: {{ toggle(name, enabled) {{ enabled ? bodyClasses.add(name) : bodyClasses.delete(name); }} }} }},
              getElementById(id) {{ return id === 'primaryNavigation' ? nav : id === 'mobileNavToggle' ? toggle : null; }},
              querySelectorAll() {{ return []; }},
            }};
            navigation.setMobileNavExpanded(doc, true);
            assert.equal(classes.has('is-open'), true);
            assert.equal(bodyClasses.has('mobile-nav-open'), true);
            assert.equal(attrs['aria-expanded'], 'true');
            assert.equal(attrs['aria-label'], '关闭导航菜单');
            navigation.setMobileNavExpanded(doc, false);
            assert.equal(classes.has('is-open'), false);
            assert.equal(bodyClasses.has('mobile-nav-open'), false);
            assert.equal(attrs['aria-expanded'], 'false');
            """
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recent_download_toolbar_preserves_single_line_button_labels(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertIn('class="actions recent-items-actions"', index)
        self.assertIn("#recent-items .panel-head > .recent-items-actions", styles)
        self.assertIn("#recent-items .recent-items-actions > #openQbit { min-width: 148px; }", styles)
        self.assertIn("#recent-items .recent-items-actions > #normalizeTorrents { min-width: 132px; }", styles)
        self.assertIn("#recent-items .recent-items-actions > #clearRecentItems { min-width: 96px; }", styles)
        self.assertIn("white-space: nowrap;", styles)
        self.assertIn("flex-wrap: wrap;", styles)

    def test_download_table_has_mobile_card_labels(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertIn('class="responsive-table"', index)
        for label in ("时间", "标题", "集数", "状态", "命名", "说明", "操作"):
            self.assertIn(f"dataset.label = '{label}'", script)
        self.assertIn(".responsive-table td::before", styles)
        self.assertIn("content: attr(data-label)", styles)


if __name__ == "__main__":
    unittest.main()
