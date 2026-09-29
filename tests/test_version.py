"""
Unittests für das Versionsmodul und die Versionsermittlung.
"""

import unittest
from unittest.mock import patch
import re
from src.__version__ import get_app_version, __version__


class TestAppVersion(unittest.TestCase):

    def test_version_format(self):
        self.assertTrue(bool(re.match(r"^v\d+\.\d+\.\d+", __version__)))

    def test_get_app_version_returns_valid_tag(self):
        version = get_app_version()
        self.assertTrue(version.startswith("v"))
        self.assertIn(".", version)

    @patch("src.__version__.subprocess.run")
    def test_get_app_version_fallback_on_error(self, mock_run):
        # Cache leeren für isolierten Test
        get_app_version.cache_clear()
        mock_run.side_effect = FileNotFoundError("git not found")
        
        fallback_version = get_app_version()
        self.assertEqual(fallback_version, __version__)
        get_app_version.cache_clear()


if __name__ == "__main__":
    unittest.main()
