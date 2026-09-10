from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopPortalContractTest(unittest.TestCase):
    def test_top_right_website_and_miniprogram_actions_are_present(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="officialWebsiteBtn"', html)
        self.assertIn('href="https://shuiliyingxiang.cn/"', html)
        self.assertIn('id="miniProgramPortalBtn"', html)
        self.assertIn('id="miniProgramPopover"', html)
        self.assertIn('aria-controls="miniProgramPopover"', html)
        self.assertIn('src="/assets/miniprogram_qr.png"', html)
        self.assertIn("event.key === 'Escape'", html)

    def test_miniprogram_code_asset_is_shipped(self):
        image = ROOT / "assets" / "miniprogram_qr.png"
        self.assertTrue(image.is_file())
        self.assertGreater(image.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
