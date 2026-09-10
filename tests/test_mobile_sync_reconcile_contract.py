# -*- coding: utf-8 -*-
"""Contract checks for the temporary full-inventory reconciliation patch.

These tests deliberately inspect the patch source instead of importing it: importing
``mobile_sync_reconcile`` monkey-patches ``mobile_sync.DesktopMobileSync`` process-wide
and would change the behavior of the normal mobile_sync regression suite.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "mobile_sync_reconcile.py"


class MobileSyncReconcileContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATCH_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _constant(self, name):
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        return ast.literal_eval(node.value)
        self.fail(f"missing module constant: {name}")

    def test_accelerated_scan_keeps_existing_revision_progress(self):
        self.assertEqual(
            self._constant("RECONCILE_REVISION"),
            "desktop-full-inventory-v1-20260910",
        )
        self.assertGreaterEqual(self._constant("MIN_BACKFILL_BATCH"), 200)

    def test_network_attempt_is_charged_only_once(self):
        self.assertIn("if attempted >= self.backfill_limit:", self.source)
        self.assertNotIn("if attempted + verified >= self.backfill_limit:", self.source)

    def test_mobile_origin_risk_set_is_processed_first(self):
        self.assertIn(
            'candidates.sort(key=lambda item: 0 if item.get("mobile_origin") else 1)',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
