"""Tests calternos_store (normalización sin MySQL)."""

import unittest

from db.calternos_store import CHIJO_MAX_LEN, normalize_codigos_alternos


class TestNormalizeCodigosAlternos(unittest.TestCase):
    def test_empty_and_none(self):
        self.assertEqual(normalize_codigos_alternos(None), [])
        self.assertEqual(normalize_codigos_alternos([]), [])

    def test_trims_and_dedupes(self):
        self.assertEqual(
            normalize_codigos_alternos([" 7591 ", "7591", "7592637005099"]),
            ["7591", "7592637005099"],
        )

    def test_skips_blank_entries(self):
        self.assertEqual(normalize_codigos_alternos(["", "  ", "7591"]), ["7591"])

    def test_rejects_too_long(self):
        long_code = "1" * (CHIJO_MAX_LEN + 1)
        with self.assertRaises(ValueError):
            normalize_codigos_alternos([long_code])


if __name__ == "__main__":
    unittest.main()
