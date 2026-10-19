"""K5: one publisher name, a UTF-8 + PerMonitorV2 manifest, and no omw-1.4 in the bundle.
Reads the build files; nothing is built here."""
import os
import re
import unittest
import xml.dom.minidom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as handle:
        return handle.read()


class TestPackaging(unittest.TestCase):
    def test_publisher_is_the_same_everywhere(self):
        self.assertIn("StringStruct('CompanyName', 'MELEJ')", _read("storyforge.spec"))
        self.assertIn("AppPublisher=MELEJ", _read("installer", "StoryForge.iss"))

    def test_manifest_declares_utf8_and_per_monitor_v2(self):
        spec = _read("storyforge.spec")
        self.assertIn("manifest=MANIFEST_FILE", spec)
        manifest = re.search(r'_f\.write\("""(<\?xml.*?</assembly>\n)"""\)', spec, re.S).group(1)
        dom = xml.dom.minidom.parseString(manifest)
        self.assertEqual(dom.getElementsByTagName("activeCodePage")[0].firstChild.data, "UTF-8")
        self.assertEqual(dom.getElementsByTagName("dpiAwareness")[0].firstChild.data, "PerMonitorV2")

    def test_omw_is_left_out_of_the_bundle(self):
        spec = _read("storyforge.spec")
        self.assertIn('if _name.startswith("omw")', spec)
        self.assertNotIn('datas.append(("nltk_data", "nltk_data"))', spec)


if __name__ == "__main__":
    unittest.main()
