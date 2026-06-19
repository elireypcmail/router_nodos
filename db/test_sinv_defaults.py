"""Tests defaults sinv al crear producto."""

import unittest

from db.sinv_store import SINV_DEFAULT_UXB, prepare_sinv_upsert


class TestSinvDefaults(unittest.TestCase):
    def test_prepare_sinv_upsert_defaults_uxb_to_one(self):
        row = prepare_sinv_upsert({"codigo": "A1"})
        self.assertEqual(row["uxb"], SINV_DEFAULT_UXB)

    def test_prepare_sinv_upsert_keeps_custom_uxb(self):
        row = prepare_sinv_upsert({"codigo": "A2", "uxb": 12})
        self.assertEqual(row["uxb"], 12.0)


if __name__ == "__main__":
    unittest.main()
