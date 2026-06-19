"""Tests sinvimg_store (sin MySQL)."""

import base64
import unittest

from db.sinvimg_store import decode_imagen_base64, detect_content_type, encode_imagen_base64

# Minimal valid 1x1 JPEG
_JPEG_BYTES = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAb/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
    "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA//2Q=="
)


class TestSinvimgStore(unittest.TestCase):
    def test_detect_jpeg(self):
        self.assertEqual(detect_content_type(_JPEG_BYTES), "image/jpeg")

    def test_decode_plain_base64(self):
        encoded = base64.b64encode(_JPEG_BYTES).decode("ascii")
        self.assertEqual(decode_imagen_base64(encoded), _JPEG_BYTES)

    def test_decode_data_url(self):
        encoded = base64.b64encode(_JPEG_BYTES).decode("ascii")
        data_url = f"data:image/jpeg;base64,{encoded}"
        self.assertEqual(decode_imagen_base64(data_url), _JPEG_BYTES)

    def test_encode_roundtrip(self):
        encoded = encode_imagen_base64(_JPEG_BYTES)
        self.assertEqual(decode_imagen_base64(encoded), _JPEG_BYTES)

    def test_rejects_invalid_base64(self):
        with self.assertRaises(ValueError):
            decode_imagen_base64("not-base64!!!")


if __name__ == "__main__":
    unittest.main()
