# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import unittest
from unittest.mock import patch

import bump_version
import prepare_release_version


class ReleaseVersioningTest(unittest.TestCase):
    def test_online_reset_version_is_corrected_to_three_zero(self):
        value = prepare_release_version._next_version(
            "A20260912-2.1", "A20260910-2.92"
        )
        self.assertTrue(value.endswith("-3.0"), value)

    def test_display_version_carries_after_nine_and_never_resets_on_new_date(self):
        fixed_date = datetime.date(2026, 9, 12)
        with patch.object(bump_version.datetime, "date") as mocked_date:
            mocked_date.today.return_value = fixed_date
            self.assertEqual(bump_version.next_version("A20260911-2.9"), "A20260912-3.0")
            self.assertEqual(bump_version.next_version("A20260911-3.0"), "A20260912-3.1")
            self.assertEqual(bump_version.next_version("A20260911-3.9"), "A20260912-4.0")

    def test_ci_version_continues_after_three_zero(self):
        value = prepare_release_version._next_version(
            "A20260912-3.0", "A20260910-2.92"
        )
        self.assertTrue(value.endswith("-3.1"), value)


if __name__ == "__main__":
    unittest.main()
