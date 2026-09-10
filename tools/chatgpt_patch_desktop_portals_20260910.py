from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one marker, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


index = Path("templates/index.html")

stylesheet = '  <link rel="stylesheet" href="/assets/app-A20260910-2.92.css">\n'
portal_css = stylesheet + r'''  <style id="desktopPortalStyles">
    .top-actions { position: relative; }
    .top-actions .desktop-portal-action {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      padding: 0 12px;
      border: 1px solid rgba(255,255,255,.24);
      border-radius: 8px;
      color: #fff;
      background: rgba(255,255,255,.14);
      font-size: 13px;
      font-weight: 650;
      line-height: 1;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
      box-sizing: border-box;
      transition: background .18s ease, border-color .18s ease, box-shadow .18s ease, transform .18s ease;
    }
    .top-actions .desktop-portal-action:hover,
    .top-actions .desktop-portal-action:focus-visible {
      color: #fff;
      background: rgba(255,255,255,.25);
      border-color: rgba(255,255,255,.38);
      box-shadow: 0 7px 16px rgba(4,32,42,.13);
      transform: translateY(-1px);
      outline: none;
    }
    .top-actions .desktop-portal-action:active { transform: translateY(0) scale(.98); }
    .mini-program-popover {
      position: absolute;
      top: calc(100% + 12px);
      right: 0;
      z-index: 90;
      width: min(326px, calc(100vw - 24px));
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      color: var(--text);
      background: var(--panel);
      box-shadow: 0 20px 52px rgba(4,32,42,.24);
      box-sizing: border-box;
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
      transform: translateY(-8px) scale(.985);
      transform-origin: top right;
      transition: opacity .16s ease, transform .16s ease, visibility .16s ease;
    }
    .mini-program-popover.open {
      opacity: 1;
      visibility: visible;
      pointer-events: auto;
      transform: translateY(0) scale(1);
    }
    .mini-program-popover::before {
      content: "";
      position: absolute;
      top: -7px;
      right: 46px;
      width: 12px;
      height: 12px;
      border-left: 1px solid var(--line);
      border-top: 1px solid var(--line);
      background: var(--panel);
      transform: rotate(45deg);
    }
    .mini-program-popover-head {
      position: relative;
      z-index: 1;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .mini-program-popover-title { display: block; color: var(--text); font-size: 16px; font-weight: 700; }
    .mini-program-popover-subtitle { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; line-height: 1.4; }
    .top-actions .mini-program-popover-close {
      display: grid;
      place-items: center;
      flex: 0 0 auto;
      width: 30px;
      height: 30px;
      min-height: 30px;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--muted);
      background: var(--panel-soft);
      box-shadow: none;
      font-size: 20px;
      line-height: 1;
    }
    .top-actions .mini-program-popover-close:hover {
      color: var(--text);
      background: var(--primary-2);
      border-color: var(--line-strong);
      transform: none;
      box-shadow: none;
    }
    .mini-program-qr-shell {
      display: grid;
      place-items: center;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
    }
    .mini-program-qr-shell img {
      display: block;
      width: min(260px, 100%);
      height: auto;
      aspect-ratio: 1 / 1;
      object-fit: contain;
    }
    .mini-program-popover-note {
      margin: 11px 2px 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
      text-align: center;
    }
    @media (max-width: 980px) {
      .top-actions .desktop-portal-action { padding: 0 10px; }
      .mini-program-popover { position: fixed; top: 66px; right: 12px; }
      .mini-program-popover::before { display: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      .top-actions .desktop-portal-action, .mini-program-popover { transition: none; }
    }
  </style>
'''
replace_once(index, stylesheet, portal_css)

version_marker = '        <span class="app-version-badge" id="appVersionBadge" title="当前软件版本"></span>\n'
portal_html = version_marker + r'''        <a id="officialWebsiteBtn" class="desktop-portal-action" href="https://shuiliyingxiang.cn/" target="_blank" rel="noopener noreferrer" title="打开工程影像官网">官网</a>
        <button id="miniProgramPortalBtn" class="desktop-portal-action" type="button" aria-expanded="false" aria-controls="miniProgramPopover" title="打开工程影像小程序码">小程序</button>
        <div id="miniProgramPopover" class="mini-program-popover" aria-hidden="true" role="dialog" aria-label="工程影像小程序">
          <div class="mini-program-popover-head">
            <div>
              <strong class="mini-program-popover-title">工程影像小程序</strong>
              <span class="mini-program-popover-subtitle">微信扫码进入现场采集端</span>
            </div>
            <button type="button" id="miniProgramPopoverClose" class="mini-program-popover-close" aria-label="关闭小程序码">×</button>
          </div>
          <div class="mini-program-qr-shell">
            <img src="/assets/miniprogram_qr.png" alt="工程影像微信小程序码" width="320" height="320">
          </div>
          <p class="mini-program-popover-note">用于现场拍照、上传和查看工程影像。</p>
        </div>
'''
replace_once(index, version_marker, portal_html)

script_marker = '  <script defer src="/assets/app-A20260910-2.92.js"></script>\n'
portal_script = r'''  <script>
    (() => {
      const initDesktopPortals = () => {
        const button = document.getElementById('miniProgramPortalBtn');
        const popover = document.getElementById('miniProgramPopover');
        const closeButton = document.getElementById('miniProgramPopoverClose');
        if (!button || !popover || !closeButton) return;

        const setOpen = (open) => {
          popover.classList.toggle('open', open);
          popover.setAttribute('aria-hidden', open ? 'false' : 'true');
          button.setAttribute('aria-expanded', open ? 'true' : 'false');
        };

        button.addEventListener('click', (event) => {
          event.stopPropagation();
          setOpen(!popover.classList.contains('open'));
        });
        closeButton.addEventListener('click', (event) => {
          event.stopPropagation();
          setOpen(false);
          button.focus();
        });
        popover.addEventListener('click', (event) => event.stopPropagation());
        document.addEventListener('click', () => setOpen(false));
        document.addEventListener('keydown', (event) => {
          if (event.key === 'Escape' && popover.classList.contains('open')) {
            setOpen(false);
            button.focus();
          }
        });
      };
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDesktopPortals, { once: true });
      } else {
        initDesktopPortals();
      }
    })();
  </script>
''' + script_marker
replace_once(index, script_marker, portal_script)

Path("tests/test_desktop_portals.py").write_text(r'''from pathlib import Path
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
''', encoding="utf-8")

print("desktop website + mini-program portal patch applied")
