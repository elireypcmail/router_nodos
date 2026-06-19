"""Tests alícuota porvg permitida."""

import unittest

from db.product_porvg import validate_porvg


class TestProductPorvg(unittest.TestCase):
    def test_allowed_values(self):
        for v in (0, 8, 16, 31):
            self.assertEqual(validate_porvg(v), float(v))

    def test_none_ok(self):
        self.assertIsNone(validate_porvg(None))

    def test_rejects_invalid(self):
        with self.assertRaises(ValueError):
            validate_porvg(33)


if __name__ == "__main__":
    unittest.main()
