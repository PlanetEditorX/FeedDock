from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path

from app.mikan_subscription import (
    collect_subscribed_mikan_bangumi_ids,
    extract_mikan_bangumi_id,
)


ROOT = Path(__file__).resolve().parents[1]


class MikanSubscriptionStateTests(unittest.TestCase):
    def test_extracts_case_insensitive_bangumi_id(self) -> None:
        self.assertEqual(
            extract_mikan_bangumi_id(
                "https://mikanime.tv/RSS/Bangumi?subgroupid=7&BangumiID=123"
            ),
            123,
        )

    def test_rejects_missing_non_numeric_and_non_positive_ids(self) -> None:
        for value in (
            None,
            "",
            "https://mikanime.tv/RSS/Bangumi?subgroupid=7",
            "https://mikanime.tv/RSS/Bangumi?bangumiId=abc",
            "https://mikanime.tv/RSS/Bangumi?bangumiId=0",
            "https://mikanime.tv/RSS/Bangumi?bangumiId=-3",
        ):
            with self.subTest(value=value):
                self.assertEqual(extract_mikan_bangumi_id(value), 0)

    def test_collects_primary_and_backup_rss_without_duplicates(self) -> None:
        rows = [
            (
                "https://mikanime.tv/RSS/Bangumi?bangumiId=11",
                "https://mikanani.me/RSS/Bangumi?BangumiId=12",
            ),
            (
                "https://mikanime.tv/RSS/Bangumi?bangumiId=11&subgroupid=2",
                "not-a-mikan-feed",
            ),
        ]
        self.assertEqual(collect_subscribed_mikan_bangumi_ids(rows), {11, 12})

    def test_frontend_module_handles_urls_and_mutates_only_changed_items(self) -> None:
        module_path = ROOT / "app/static/mikan-subscription-state.js"
        script = textwrap.dedent(
            f"""
            const assert = require('node:assert/strict');
            const state = require({str(module_path)!r});

            assert.equal(
              state.extractBangumiId('https://mikanime.tv/RSS/Bangumi?BangumiID=123'),
              123,
            );
            assert.equal(state.extractBangumiId('?bangumiId=88', 'https://mikanime.tv'), 88);
            assert.equal(state.extractBangumiId('https://mikanime.tv/RSS/Bangumi?bangumiId=12x'), 0);

            const ids = state.collectSubscribedBangumiIds([
              {{ rss_url: 'https://mikanime.tv/RSS/Bangumi?bangumiId=1' }},
              {{ backup_rss_url: 'https://mikanani.me/RSS/Bangumi?BANGUMIID=2' }},
              null,
            ]);
            assert.deepEqual([...ids].sort((a, b) => a - b), [1, 2]);

            const catalog = {{ rows: [{{ items: [
              {{ bangumi_id: 1, subscribed: false }},
              {{ bangumi_id: 2, subscribed: true }},
              {{ bangumi_id: 3, subscribed: true }},
            ] }}] }};
            assert.equal(state.updateCatalogSubscriptionState(catalog, ids), 2);
            assert.deepEqual(
              catalog.rows[0].items.map((item) => item.subscribed),
              [true, true, false],
            );
            assert.equal(state.updateCatalogSubscriptionState(catalog, ids), 0);
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
