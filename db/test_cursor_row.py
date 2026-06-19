"""Tests cursor_row helper."""

import unittest

from db.cursor_row import cursor_row_as_dict


class TestCursorRow(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(cursor_row_as_dict(None, ("a", "b")))

    def test_dict_passthrough(self):
        row = {"codigo": "A1", "costopro": 10}
        self.assertEqual(cursor_row_as_dict(row, ("codigo", "costopro")), row)

    def test_tuple_to_dict(self):
        row = ("A1", 0, 12.5, 0, 0, 70, 0, 0, 0, 70, 0, 0, 0)
        cols = (
            "codigo",
            "costo",
            "costopro",
            "costoant",
            "cambiodc",
            "pg1",
            "pg2",
            "pg3",
            "pg4",
            "precio1",
            "precio2",
            "precio3",
            "precio4",
        )
        out = cursor_row_as_dict(row, cols)
        self.assertEqual(out["codigo"], "A1")
        self.assertEqual(out["costopro"], 12.5)
        self.assertEqual(out["pg1"], 70)


if __name__ == "__main__":
    unittest.main()
