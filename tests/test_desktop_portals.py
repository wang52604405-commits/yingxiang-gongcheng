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
        from PIL import Image

        image = ROOT / "assets" / "miniprogram_qr.png"
        self.assertTrue(image.is_file())
        self.assertGreater(image.stat().st_size, 10_000)
        with Image.open(image) as decoded:
            decoded.load()
            self.assertEqual(decoded.size, (430, 430))

        site_image = ROOT / "website" / "assets" / "miniprogram_qr.png"
        self.assertTrue(site_image.is_file())
        with Image.open(site_image) as decoded:
            decoded.load()
            self.assertEqual(decoded.size, (430, 430))

    def test_website_displays_the_same_miniprogram_code_without_cropping(self):
        html = (ROOT / "website" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "website" / "assets" / "style.css").read_text(encoding="utf-8")
        self.assertIn('src="assets/miniprogram_qr.png"', html)
        self.assertIn("mini-program-site-code", html)
        self.assertIn('href="#mini-program"', html)
        self.assertIn(">微信小程序<", html)
        self.assertIn("object-fit:contain", css)


if __name__ == "__main__":
    unittest.main()
