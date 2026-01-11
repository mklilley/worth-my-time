import json
import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.bookmarks import load_brave_inbox_bookmarks


class BookmarksParsingTests(unittest.TestCase):
    def test_loads_inbox_urls_under_bookmark_bar(self) -> None:
        data = {
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "children": [
                        {
                            "type": "folder",
                            "name": "Inbox",
                            "children": [
                                {
                                    "type": "url",
                                    "name": "Example",
                                    "url": "https://example.com",
                                    "guid": "abc",
                                    "id": "123",
                                    "date_added": "13412614145662919",
                                }
                            ],
                        }
                    ],
                }
            }
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "Bookmarks"
            path.write_text(json.dumps(data), encoding="utf-8")
            items = load_brave_inbox_bookmarks(bookmarks_path=path, inbox_folder_name="Inbox", root_name="bookmark_bar")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].url, "https://example.com")
            self.assertEqual(items[0].title, "Example")
            self.assertIsNotNone(items[0].date_added)


if __name__ == "__main__":
    unittest.main()
