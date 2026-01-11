import unittest

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.urls import normalize_url


class UrlNormalizationTests(unittest.TestCase):
    def test_drops_utm_and_fragment(self) -> None:
        url = "https://example.com/a/b?utm_source=x&x=1#section"
        self.assertEqual(normalize_url(url), "https://example.com/a/b?x=1")

    def test_canonicalizes_youtube_watch(self) -> None:
        url = "https://www.youtube.com/watch?v=abc123&t=10s&utm_source=x"
        self.assertEqual(normalize_url(url), "https://www.youtube.com/watch?v=abc123")

    def test_canonicalizes_youtu_be(self) -> None:
        url = "https://youtu.be/abc123?t=10"
        self.assertEqual(normalize_url(url), "https://www.youtube.com/watch?v=abc123")


if __name__ == "__main__":
    unittest.main()
