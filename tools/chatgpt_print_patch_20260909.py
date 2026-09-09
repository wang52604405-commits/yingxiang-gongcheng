# -*- coding: utf-8 -*-
"""One-time guarded patch for the A4 photo printing UX.

Goals:
- paper orientation is an independent landscape/portrait segmented choice;
- caption output is an independent inline/separate-page segmented choice;
- visible layouts are exactly 1 / 2 / 4 / custom;
- all layouts allocate fixed A4 cells first, then fit the photo inside each cell;
- captions can never push another photo off the sheet;
- custom layouts are centered and auto-fill their cells too.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
APP = ROOT / "app.py"
HTML = ROOT / "templates" / "index.html"
PRINT_HTML = ROOT / "templates" / "print.html"
JS = ROOT / "assets" / "app-A20260908-2.89.js"
CSS = ROOT / "assets" / "app-A20260908-2.89.css"
TEST = ROOT / "tests" / "test_z_print_layout_modes.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"patch anchor missing: {label}")


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count == 1:
        return updated
    if replacement in text:
        return text
    raise SystemExit(f"patch regex missing: {label}")


# ---------------------------------------------------------------------------
# Backend settings + layout engine
# ---------------------------------------------------------------------------
app = read(APP)
app = replace_once(
    app,
    '    "print_caption_position": "bottom",\n    "print_caption_size_mm": 7.5,',
    '    "print_caption_position": "bottom",\n    "print_caption_mode": "inline",\n    "print_auto_fill": True,\n    "print_caption_size_mm": 7.5,',
    "default print caption mode",
)

read_norm = '    settings["print_caption_position"] = settings.get("print_caption_position") if settings.get("print_caption_position") in {"hidden", "left", "right", "top", "bottom"} else "bottom"\n'
read_norm_new = read_norm + '    settings["print_caption_mode"] = settings.get("print_caption_mode") if settings.get("print_caption_mode") in {"inline", "separate"} else "inline"\n    settings["print_auto_fill"] = bool(settings.get("print_auto_fill", True))\n'
app = replace_once(app, read_norm, read_norm_new, "normalize persisted print mode")

write_norm = '    current["print_caption_position"] = payload.get("print_caption_position") if payload.get("print_caption_position") in {"hidden", "left", "right", "top", "bottom"} else current.get("print_caption_position", "bottom")\n'
write_norm_new = write_norm + '    requested_caption_mode = payload.get("print_caption_mode", current.get("print_caption_mode", "inline"))\n    current["print_caption_mode"] = requested_caption_mode if requested_caption_mode in {"inline", "separate"} else "inline"\n    if "print_auto_fill" in payload:\n        current["print_auto_fill"] = bool(payload.get("print_auto_fill"))\n'
app = replace_once(app, write_norm, write_norm_new, "save print mode")

style_defaults = r'''PRINT_STYLE_DEFAULTS = {
    # New visible print presets. Paper direction and caption output mode are
    # intentionally NOT baked into these presets; the UI sends those as two
    # independent segmented choices.
    "one": {
        "print_page_size": 1,
        "print_single_alignment": "center",
        "print_photo_preset": "custom",
        "print_photo_width_cm": 1.0,
        "print_photo_height_cm": 1.0,
        "print_caption_position": "bottom",
        "print_caption_size_mm": 7.5,
        "print_caption_font_size": 10.0,
        "print_margin_top_mm": 6.0,
        "print_margin_right_mm": 6.0,
        "print_margin_bottom_mm": 6.0,
        "print_margin_left_mm": 6.0,
        "print_horizontal_gap_mm": 2.0,
        "print_vertical_gap_mm": 2.0,
        "print_image_fit": "contain",
        "print_show_page_title": True,
        "print_auto_fill": True,
    },
    "two": {
        "print_page_size": 2,
        "print_single_alignment": "center",
        "print_photo_preset": "custom",
        "print_photo_width_cm": 1.0,
        "print_photo_height_cm": 1.0,
        "print_caption_position": "bottom",
        "print_caption_size_mm": 7.5,
        "print_caption_font_size": 10.0,
        "print_margin_top_mm": 6.0,
        "print_margin_right_mm": 6.0,
        "print_margin_bottom_mm": 6.0,
        "print_margin_left_mm": 6.0,
        "print_horizontal_gap_mm": 3.0,
        "print_vertical_gap_mm": 3.0,
        "print_image_fit": "contain",
        "print_show_page_title": True,
        "print_auto_fill": True,
    },
    "four": {
        "print_page_size": 4,
        "print_single_alignment": "center",
        "print_photo_preset": "custom",
        "print_photo_width_cm": 1.0,
        "print_photo_height_cm": 1.0,
        "print_caption_position": "bottom",
        "print_caption_size_mm": 7.5,
        "print_caption_font_size": 10.0,
        "print_margin_top_mm": 5.0,
        "print_margin_right_mm": 5.0,
        "print_margin_bottom_mm": 5.0,
        "print_margin_left_mm": 5.0,
        "print_horizontal_gap_mm": 3.0,
        "print_vertical_gap_mm": 3.0,
        "print_image_fit": "contain",
        "print_show_page_title": True,
        "print_auto_fill": True,
    },
    # Compatibility aliases for old saved/bookmarked links. They now use the
    # safe cell allocator instead of fixed 18.5x12.3cm dimensions.
    "default": {"print_layout": "landscape", "print_page_size": 4, "print_photo_preset": "custom", "print_photo_width_cm": 1.0, "print_photo_height_cm": 1.0, "print_caption_position": "bottom", "print_caption_size_mm": 7.5, "print_caption_font_size": 10.0, "print_margin_top_mm": 5.0, "print_margin_right_mm": 5.0, "print_margin_bottom_mm": 5.0, "print_margin_left_mm": 5.0, "print_horizontal_gap_mm": 3.0, "print_vertical_gap_mm": 3.0, "print_image_fit": "contain", "print_show_page_title": True, "print_auto_fill": True},
    "portrait2": {"print_layout": "portrait", "print_page_size": 2, "print_photo_preset": "custom", "print_photo_width_cm": 1.0, "print_photo_height_cm": 1.0, "print_caption_position": "bottom", "print_caption_size_mm": 7.5, "print_caption_font_size": 10.0, "print_margin_top_mm": 6.0, "print_margin_right_mm": 6.0, "print_margin_bottom_mm": 6.0, "print_margin_left_mm": 6.0, "print_horizontal_gap_mm": 3.0, "print_vertical_gap_mm": 3.0, "print_image_fit": "contain", "print_show_page_title": True, "print_auto_fill": True},
    "landscape2": {"print_layout": "landscape", "print_page_size": 2, "print_photo_preset": "custom", "print_photo_width_cm": 1.0, "print_photo_height_cm": 1.0, "print_caption_position": "bottom", "print_caption_size_mm": 7.5, "print_caption_font_size": 10.0, "print_margin_top_mm": 6.0, "print_margin_right_mm": 6.0, "print_margin_bottom_mm": 6.0, "print_margin_left_mm": 6.0, "print_horizontal_gap_mm": 3.0, "print_vertical_gap_mm": 3.0, "print_image_fit": "contain", "print_show_page_title": True, "print_auto_fill": True},
    "single": {"print_layout": "landscape", "print_page_size": 1, "print_single_alignment": "center", "print_photo_preset": "custom", "print_photo_width_cm": 1.0, "print_photo_height_cm": 1.0, "print_caption_position": "bottom", "print_caption_size_mm": 7.5, "print_caption_font_size": 10.0, "print_margin_top_mm": 6.0, "print_margin_right_mm": 6.0, "print_margin_bottom_mm": 6.0, "print_margin_left_mm": 6.0, "print_horizontal_gap_mm": 2.0, "print_vertical_gap_mm": 2.0, "print_image_fit": "contain", "print_show_page_title": True, "print_auto_fill": True},
}


def print_layout_from_request'''
app = regex_once(
    app,
    r'PRINT_STYLE_DEFAULTS = \{.*?\n\}\n\n\ndef print_layout_from_request',
    style_defaults,
    "print style defaults",
)

request_mode_anchor = '    settings["print_caption_position"] = position if position in {"hidden", "left", "right", "top", "bottom"} else "bottom"\n'
request_mode_new = request_mode_anchor + '''    caption_mode = str(request.args.get("caption_mode") or settings.get("print_caption_mode") or "inline").strip().lower()
    settings["print_caption_mode"] = caption_mode if caption_mode in {"inline", "separate"} else "inline"
    auto_fill_raw = str(request.args.get("auto_fill", "1" if settings.get("print_auto_fill", True) else "0")).strip().lower()
    settings["print_auto_fill"] = auto_fill_raw not in {"0", "false", "no", "off"}
'''
app = replace_once(app, request_mode_anchor, request_mode_new, "request caption mode and autofill")

new_layout_function = r'''def layout_fixed_photo_pages(photos, layout="landscape", page_size=4, photo_width_mm=None, photo_height_mm=None, print_settings=None):
    """Lay out photos by allocating A4 cells first, then fitting each item inside.

    This removes the old failure mode where a fixed photo size plus a bottom
    caption exceeded the sheet and silently forced the second photo onto a new
    page. For 1/2/4 presets the grid is deterministic; custom counts choose the
    grid that best fits a 4:3 photo. Every block is centered inside its cell.
    """
    settings = print_settings or {}
    try:
        page_size = max(1, min(12, int(page_size or 4)))
    except (TypeError, ValueError):
        page_size = 4
    margin_top = float(settings.get("print_margin_top_mm", 6.0))
    margin_right = float(settings.get("print_margin_right_mm", 6.0))
    margin_bottom = float(settings.get("print_margin_bottom_mm", 6.0))
    margin_left = float(settings.get("print_margin_left_mm", 6.0))
    horizontal_gap = float(settings.get("print_horizontal_gap_mm", PRINT_FIXED_GAP))
    vertical_gap = float(settings.get("print_vertical_gap_mm", PRINT_FIXED_GAP))
    caption_position = str(settings.get("print_caption_position") or "bottom")
    caption_mode = str(settings.get("print_caption_mode") or "inline")
    caption_size = float(settings.get("print_caption_size_mm", 7.5))
    show_page_title = bool(settings.get("print_show_page_title", True))
    single_alignment = str(settings.get("print_single_alignment") or "center")
    auto_fill = bool(settings.get("print_auto_fill", True))

    if layout == "portrait":
        paper_w, paper_h = 210.0, 297.0
    else:
        paper_w, paper_h = 297.0, 210.0
    page_w = max(20.0, paper_w - margin_left - margin_right)
    title_h = 7.0 if show_page_title else 0.0
    page_h = max(20.0, paper_h - margin_top - margin_bottom - title_h)

    if page_size == 1:
        cols, rows = 1, 1
    elif page_size == 2:
        cols, rows = ((1, 2) if layout == "portrait" else (2, 1))
    elif page_size == 4:
        cols, rows = 2, 2
    else:
        best = None
        for candidate_cols in range(1, page_size + 1):
            candidate_rows = (page_size + candidate_cols - 1) // candidate_cols
            cell_w = (page_w - horizontal_gap * (candidate_cols - 1)) / candidate_cols
            cell_h = (page_h - vertical_gap * (candidate_rows - 1)) / candidate_rows
            if cell_w <= 0 or cell_h <= 0:
                continue
            # Score by the largest 4:3 image that can fit in the cell, then area.
            scale = min(cell_w / 4.0, cell_h / 3.0)
            score = (scale, cell_w * cell_h)
            if best is None or score > best[0]:
                best = (score, candidate_cols, candidate_rows)
        _, cols, rows = best or ((0, 0), 1, page_size)

    cell_w = max(10.0, (page_w - horizontal_gap * (cols - 1)) / cols)
    cell_h = max(10.0, (page_h - vertical_gap * (rows - 1)) / rows)
    requested_w = float(photo_width_mm or PHOTO_5IN_LANDSCAPE[0])
    requested_h = float(photo_height_mm or PHOTO_5IN_LANDSCAPE[1])
    single_line = page_size >= 4
    pages = []

    for page_start in range(0, len(photos), page_size):
        current = []
        page_photos = photos[page_start:page_start + page_size]
        for slot, photo in enumerate(page_photos):
            row = slot // cols
            col = slot % cols
            cell_left = col * (cell_w + horizontal_gap)
            cell_top = row * (cell_h + vertical_gap)

            detail_rows = photo.get("detail_rows") or []
            has_inline_caption = bool(detail_rows) and caption_mode != "separate" and caption_position != "hidden"
            caption_extent = max(
                caption_size,
                _print_caption_h(photo, single_line=single_line),
            ) if has_inline_caption else 0.0

            if has_inline_caption and caption_position in {"left", "right"}:
                caption_w = min(max(32.0, caption_extent), max(0.0, cell_w * 0.38))
                caption_h = cell_h
                available_w = max(10.0, cell_w - caption_w)
                available_h = cell_h
            elif has_inline_caption:
                caption_h = min(caption_extent, max(0.0, cell_h * 0.35))
                caption_w = cell_w
                available_w = cell_w
                available_h = max(10.0, cell_h - caption_h)
            else:
                caption_w = 0.0
                caption_h = 0.0
                available_w = cell_w
                available_h = cell_h

            if auto_fill:
                width = available_w
                height = available_h
            else:
                width = min(max(10.0, requested_w), available_w)
                height = min(max(10.0, requested_h), available_h)

            if has_inline_caption and caption_position in {"left", "right"}:
                # Caption follows the actual custom photo height if the user opted
                # out of auto-fill; in auto-fill it naturally equals the cell.
                caption_h = height
                block_w = width + caption_w
                block_h = height
            elif has_inline_caption:
                caption_w = width
                block_w = width
                block_h = height + caption_h
            else:
                block_w = width
                block_h = height

            x = cell_left + max(0.0, (cell_w - block_w) / 2.0)
            y = cell_top + max(0.0, (cell_h - block_h) / 2.0)
            if page_size == 1 and single_alignment == "top" and not auto_fill:
                y = cell_top

            rotate = int(photo.get("rotation") or 0) % 360
            if str(photo.get("orientation") or "landscape") == "portrait":
                rotate = (rotate + 90) % 360

            item = dict(photo)
            item["_left"] = round(x, 1)
            item["_top"] = round(y, 1)
            item["_w"] = round(block_w, 1)
            item["_h"] = round(height, 1)
            item["_photo_w"] = round(width, 1)
            item["_caption_w"] = round(caption_w, 1)
            item["_block_h"] = round(block_h, 1)
            item["_caption_h"] = round(caption_h, 1)
            item["_caption_position"] = caption_position
            item["_rotate"] = rotate
            item["_cell_w"] = round(cell_w, 1)
            item["_cell_h"] = round(cell_h, 1)
            current.append(item)
        if current:
            pages.append(current)
    return pages


def assign_unique_print_page_numbers'''
app = regex_once(
    app,
    r'def layout_fixed_photo_pages\(.*?\n\s*return pages\n\n\ndef assign_unique_print_page_numbers',
    new_layout_function,
    "A4 cell layout engine",
)
write(APP, app)

# ---------------------------------------------------------------------------
# Print setup modal: independent orientation/caption segmented controls + 1/2/4/custom
# ---------------------------------------------------------------------------
html = read(HTML)
new_print_choices = r'''<div class="print-choice-stack">
                <div class="print-segment-row">
                  <span class="print-choice-label">纸张方向</span>
                  <div class="top-filter-group print-segment-group" id="printLayoutToggle" role="group" aria-label="纸张方向">
                    <button type="button" class="active" data-print-layout="landscape" aria-pressed="true">横版</button>
                    <button type="button" data-print-layout="portrait" aria-pressed="false">竖版</button>
                  </div>
                </div>
                <div class="print-segment-row">
                  <span class="print-choice-label">标签输出</span>
                  <div class="top-filter-group print-segment-group" id="printCaptionModeToggle" role="group" aria-label="标签输出方式">
                    <button type="button" class="active" data-print-caption-mode="inline" aria-pressed="true">照片下方</button>
                    <button type="button" data-print-caption-mode="separate" aria-pressed="false">标签另页</button>
                  </div>
                  <small>标签另页时，照片页只放照片；对应标签单独输出一张说明页。</small>
                </div>
              </div>
              <input id="printSetupLayout" type="hidden" value="landscape">
              <input id="printSetupCaptionMode" type="hidden" value="inline">
              <div class="print-mode-grid print-style-grid">
                <button class="print-mode-card print-style-card" type="button" data-print-style="one" aria-pressed="false">
                  <span class="print-style-schematic" aria-hidden="true"><span class="ps-paper ps-landscape ps-single"><span class="ps-slot"></span></span></span>
                  <strong>一张纸 · 1 张图</strong>
                  <span class="print-style-desc">照片按当前纸张方向自动铺满可用区域并居中</span>
                </button>
                <button class="print-mode-card print-style-card" type="button" data-print-style="two" aria-pressed="false">
                  <span class="print-style-schematic" aria-hidden="true"><span class="ps-paper ps-landscape ps-pair2"><span class="ps-slot"></span><span class="ps-slot"></span></span></span>
                  <strong>两宫格 · 2 张图</strong>
                  <span class="print-style-desc">横版左右两张；竖版上下两张，标签不会挤出下一张</span>
                </button>
                <button class="print-mode-card print-style-card" type="button" data-print-style="four" aria-pressed="false">
                  <span class="print-style-schematic" aria-hidden="true"><span class="ps-paper ps-landscape ps-grid4"><span class="ps-slot"></span><span class="ps-slot"></span><span class="ps-slot"></span><span class="ps-slot"></span></span></span>
                  <strong>四宫格 · 4 张图</strong>
                  <span class="print-style-desc">2×2 自动铺满 A4 可用区域，横版竖版均自适应</span>
                </button>
                <button class="print-mode-card print-style-card" type="button" data-print-style="custom" aria-pressed="false">
                  <span class="print-style-schematic" aria-hidden="true"><span class="ps-paper ps-landscape ps-custom"><span class="ps-slot"></span><span class="ps-slot"></span><span class="ps-slot"></span></span></span>
                  <strong>自定义</strong>
                  <span class="print-style-desc">自定义每页数量、标签、页边距和间距；照片仍自动铺满并居中</span>
                </button>
              </div>
              <div id="printCustomPanel" class="print-custom-panel">'''
html = regex_once(
    html,
    r'<div class="print-mode-grid print-style-grid">.*?</div>\s*<div id="printCustomPanel" class="print-custom-panel">',
    new_print_choices,
    "print setup choices",
)
# Hide obsolete fixed-photo-size controls without removing their IDs (old settings remain compatible).
for label_text in (
    '单张打印位置<select id="printSetupSingleAlignment"',
    '照片规格<select id="printSetupPreset"',
    '照片宽度(cm)<input id="printSetupPhotoWidth"',
    '照片高度(cm)<input id="printSetupPhotoHeight"',
):
    html = html.replace(f'<label>{label_text}', f'<label class="print-legacy-size-field">{label_text}', 1)
# The old paper-direction select is replaced by the segmented control above.
html = re.sub(
    r'<label>纸张方向<select id="printSetupLayout">.*?</select></label>',
    '',
    html,
    count=1,
    flags=re.S,
)
write(HTML, html)

# ---------------------------------------------------------------------------
# Frontend behavior
# ---------------------------------------------------------------------------
js = read(JS)
new_styles_js = r'''const PRINT_STYLES = {
      one: { style: "one", page_size: "1", single_alignment: "center", photo_preset: "custom", photo_width_cm: "1", photo_height_cm: "1", caption_position: "bottom", caption_size_mm: "7.5", caption_font_size: "10", margin_top_mm: "6", margin_right_mm: "6", margin_bottom_mm: "6", margin_left_mm: "6", horizontal_gap_mm: "2", vertical_gap_mm: "2", image_fit: "contain", show_page_title: "1", auto_fill: "1", caption_fields: "title,id,part_name,photo_date,photographer" },
      two: { style: "two", page_size: "2", single_alignment: "center", photo_preset: "custom", photo_width_cm: "1", photo_height_cm: "1", caption_position: "bottom", caption_size_mm: "7.5", caption_font_size: "10", margin_top_mm: "6", margin_right_mm: "6", margin_bottom_mm: "6", margin_left_mm: "6", horizontal_gap_mm: "3", vertical_gap_mm: "3", image_fit: "contain", show_page_title: "1", auto_fill: "1", caption_fields: "title,id,part_name,photo_date,photographer" },
      four: { style: "four", page_size: "4", single_alignment: "center", photo_preset: "custom", photo_width_cm: "1", photo_height_cm: "1", caption_position: "bottom", caption_size_mm: "7.5", caption_font_size: "10", margin_top_mm: "5", margin_right_mm: "5", margin_bottom_mm: "5", margin_left_mm: "5", horizontal_gap_mm: "3", vertical_gap_mm: "3", image_fit: "contain", show_page_title: "1", auto_fill: "1", caption_fields: "title,id,part_name,photo_date,photographer" },
      custom: null
    };'''
js = regex_once(js, r'const PRINT_STYLES = \{.*?\n\s*\};', new_styles_js, "frontend print presets")

# Load the two segmented selections from project settings.
load_anchor = '      $("#printSetupLayout").value = settings.print_layout || "landscape";\n'
load_new = load_anchor + '      $("#printSetupCaptionMode").value = settings.print_caption_mode || "inline";\n      syncPrintSegmentButtons();\n'
js = replace_once(js, load_anchor, load_new, "load segmented print choices")

segment_functions = r'''
    function syncPrintSegmentButtons() {
      const layout = $("#printSetupLayout")?.value || "landscape";
      const captionMode = $("#printSetupCaptionMode")?.value || "inline";
      document.querySelectorAll("[data-print-layout]").forEach((button) => {
        const active = button.dataset.printLayout === layout;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      document.querySelectorAll("[data-print-caption-mode]").forEach((button) => {
        const active = button.dataset.printCaptionMode === captionMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }

    function setPrintLayoutChoice(layout) {
      const value = layout === "portrait" ? "portrait" : "landscape";
      $("#printSetupLayout").value = value;
      syncPrintSegmentButtons();
    }

    function setPrintCaptionModeChoice(mode) {
      const value = mode === "separate" ? "separate" : "inline";
      $("#printSetupCaptionMode").value = value;
      syncPrintSegmentButtons();
    }

'''
if "function syncPrintSegmentButtons()" not in js:
    js = js.replace('    function loadPrintSetupValues() {\n', segment_functions + '    function loadPrintSetupValues() {\n', 1)

# Simplify style selection: exactly 1/2/4/custom; orientation and caption mode stay untouched.
select_pattern = r'    function selectPrintStyle\(style\) \{.*?\n    \}\n\n    function applyPrintStyleToPanel'
select_replacement = r'''    function selectPrintStyle(style) {
      state.printStyle = Object.prototype.hasOwnProperty.call(PRINT_STYLES, style) ? style : "custom";
      document.querySelectorAll("[data-print-style]").forEach((button) => {
        const active = button.dataset.printStyle === state.printStyle;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      const isCustom = state.printStyle === "custom";
      $("#printCustomPanel").classList.toggle("open", isCustom);
      state.pendingPrintUrl = state.printSourceUrl || state.pendingPrintUrl;
      if (!isCustom) applyPrintStyleToPanel(state.printStyle);
      syncPrintSegmentButtons();
    }

    function applyPrintStyleToPanel'''
js = regex_once(js, select_pattern, select_replacement, "select print style")

# Presets inherit current orientation and caption-mode choices. Custom is also auto-fill.
params_old = '      if (state.printStyle !== "custom" && PRINT_STYLES[state.printStyle]) return new URLSearchParams(PRINT_STYLES[state.printStyle]);\n'
params_new = '''      if (state.printStyle !== "custom" && PRINT_STYLES[state.printStyle]) {
        const params = new URLSearchParams(PRINT_STYLES[state.printStyle]);
        params.set("layout", $("#printSetupLayout").value || "landscape");
        params.set("caption_mode", $("#printSetupCaptionMode").value || "inline");
        return params;
      }
'''
js = replace_once(js, params_old, params_new, "preset dynamic parameters")
js = replace_once(
    js,
    '        layout: $("#printSetupLayout").value,\n        page_size: String(pageSize),',
    '        layout: $("#printSetupLayout").value,\n        caption_mode: $("#printSetupCaptionMode").value || "inline",\n        auto_fill: "1",\n        page_size: String(pageSize),',
    "custom caption mode and autofill",
)

# Opening the dialog selects the nearest simple grid without overriding paper direction/caption mode.
open_old = '''      // 工程设置是默认值，不应被“默认打印”预设静默覆盖。
      selectPrintStyle("custom");'''
open_new = '''      const savedPageSize = Number(state.engineeringSettings?.print_page_size || 4);
      const openingStyle = savedPageSize === 1 ? "one" : savedPageSize === 2 ? "two" : savedPageSize === 4 ? "four" : "custom";
      selectPrintStyle(openingStyle);'''
js = replace_once(js, open_old, open_new, "open print setup style")

listener_anchor = '    document.querySelectorAll("[data-print-style]").forEach((button) => button.addEventListener("click", () => selectPrintStyle(button.dataset.printStyle)));\n'
listener_new = listener_anchor + '''    document.querySelectorAll("[data-print-layout]").forEach((button) => button.addEventListener("click", () => setPrintLayoutChoice(button.dataset.printLayout)));
    document.querySelectorAll("[data-print-caption-mode]").forEach((button) => button.addEventListener("click", () => setPrintCaptionModeChoice(button.dataset.printCaptionMode)));
'''
js = replace_once(js, listener_anchor, listener_new, "segmented print listeners")
write(JS, js)

# ---------------------------------------------------------------------------
# App CSS: use the product's existing teal palette and control density
# ---------------------------------------------------------------------------
css = read(CSS)
marker = "/* print-grid-autofill-20260909 */"
if marker not in css:
    css += r'''

/* print-grid-autofill-20260909 */
.print-choice-stack {
  display: grid;
  gap: 10px;
  margin: 0 0 14px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-soft);
}
.print-segment-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.print-choice-label {
  min-width: 64px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}
.print-segment-row small {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}
.print-segment-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: #fff;
}
.print-segment-group button {
  min-width: 82px;
  min-height: 32px;
  padding: 6px 13px;
  border: 0;
  border-radius: 6px;
  color: var(--muted);
  background: transparent;
  box-shadow: none;
  transform: none;
  font-weight: 700;
}
.print-segment-group button:hover {
  color: var(--top-dark);
  background: var(--click);
  box-shadow: none;
  transform: none;
}
.print-segment-group button.active {
  color: #fff;
  background: var(--primary);
}
.print-segment-group button.active:hover { color: #fff; background: var(--top-dark); }
.print-legacy-size-field { display: none !important; }
@media (max-width: 720px) {
  .print-segment-row { align-items: flex-start; }
  .print-choice-label { width: 100%; }
  .print-segment-group { width: 100%; }
  .print-segment-group button { flex: 1; }
}
'''
write(CSS, css)

# ---------------------------------------------------------------------------
# Print template: no caption on photo sheet in separate mode; one label sheet
# follows each corresponding photo sheet.
# ---------------------------------------------------------------------------
pt = read(PRINT_HTML)
pt = replace_once(
    pt,
    '{% set caption_position = print_settings.get("print_caption_position", "bottom") %}\n',
    '{% set caption_position = print_settings.get("print_caption_position", "bottom") %}\n{% set caption_mode = print_settings.get("print_caption_mode", "inline") %}\n',
    "print template caption mode",
)
pt = replace_once(
    pt,
    '{% set style_labels = {"default": "默认 2×2", "portrait2": "竖版 · 上下双图", "landscape2": "横版 · 左右双图", "single": "横版 · 大图单张"} %}',
    '{% set style_labels = {"one": "一张纸 1 张图", "two": "两宫格", "four": "四宫格", "default": "四宫格", "portrait2": "两宫格", "landscape2": "两宫格", "single": "一张纸 1 张图"} %}',
    "print style labels",
)
pt = replace_once(
    pt,
    '{% if item.detail_rows %}\n              <div class="photo-caption">',
    '{% if caption_mode != "separate" and item.detail_rows %}\n              <div class="photo-caption">',
    "hide inline caption in separate mode",
)

# Add label sheet styling before media print.
style_anchor = '    .empty { width: 210mm; margin: 12px auto; padding: 24mm; background: #fff; color: #6b7280; text-align: center; }\n'
style_extra = style_anchor + r'''    .caption-sheet-body {
      height: calc(100% - {{ title_height }}mm);
      padding: 2mm 0 0;
      display: grid;
      grid-template-columns: repeat(var(--caption-cols, 1), minmax(0, 1fr));
      grid-auto-rows: minmax(0, 1fr);
      gap: 3mm;
      overflow: hidden;
    }
    .caption-sheet-item {
      min-height: 0;
      padding: 4mm;
      border: 1px solid #9ca3af;
      background: #fff;
      overflow: hidden;
    }
    .caption-sheet-number {
      margin: 0 0 2mm;
      padding-bottom: 1.5mm;
      border-bottom: 1px solid #d1d5db;
      font-size: 11pt;
      font-weight: 700;
    }
    .caption-sheet-row {
      margin: 0 0 1.5mm;
      font-size: 10pt;
      line-height: 1.45;
      word-break: break-word;
      overflow-wrap: anywhere;
    }
'''
pt = replace_once(pt, style_anchor, style_extra, "separate caption sheet styles")

# Toolbar description reports separate-page mode clearly.
old_tip_fragment = ' · 标签{{ {"bottom":"下方", "top":"上方", "left":"左侧", "right":"右侧", "hidden":"隐藏"}.get(caption_position, "下方") }}。系统打印中请取消页眉页脚并使用100%缩放。'
new_tip_fragment = ' · {% if caption_mode == "separate" %}标签另页{% else %}标签{{ {"bottom":"下方", "top":"上方", "left":"左侧", "right":"右侧", "hidden":"隐藏"}.get(caption_position, "下方") }}{% endif %}。系统打印中请取消页眉页脚并使用100%缩放。'
pt = replace_once(pt, old_tip_fragment, new_tip_fragment, "toolbar caption mode")

caption_sheet = r'''        </section>
        {% if caption_mode == "separate" and page_items %}
        {% set caption_cols = 1 if (page_items|length) <= 2 else (2 if (page_items|length) <= 6 else 3) %}
        <section class="page caption-sheet">
          {% if show_page_title %}<div class="title">
            <h1>{{ page_unit }}{% if group.level %} · {{ group.level }}{% endif %} · 照片标签</h1>
            <div class="meta">工程页 {{ "%03d"|format(page.print_page_number or loop.index) }} · 标签页</div>
          </div>{% endif %}
          <div class="caption-sheet-body" style="--caption-cols: {{ caption_cols }};">
            {% for item in page_items %}
            <div class="caption-sheet-item">
              <div class="caption-sheet-number">{{ item.id or ("照片 " ~ loop.index) }}</div>
              {% for row in item.detail_rows or [] %}
              <div class="caption-sheet-row"><b>{{ row.label }}：</b><span>{{ row.value }}</span></div>
              {% endfor %}
            </div>
            {% endfor %}
          </div>
        </section>
        {% endif %}
        {% endfor %}'''
pt = replace_once(
    pt,
    '        </section>\n        {% endfor %}',
    caption_sheet,
    "append separate caption sheet",
)
write(PRINT_HTML, pt)

# ---------------------------------------------------------------------------
# Regression coverage
# ---------------------------------------------------------------------------
TEST.write_text(r'''# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class PrintLayoutSourceContractTest(unittest.TestCase):
    def test_visible_print_ui_is_orientation_caption_mode_and_four_layout_choices(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        print_html = (root / "templates" / "print.html").read_text(encoding="utf-8")
        js_files = sorted((root / "assets").glob("app-A*.js"))
        css_files = sorted((root / "assets").glob("app-A*.css"))
        self.assertEqual(len(js_files), 1)
        self.assertEqual(len(css_files), 1)
        js = js_files[0].read_text(encoding="utf-8")
        css = css_files[0].read_text(encoding="utf-8")

        for marker in (
            'data-print-layout="landscape"',
            'data-print-layout="portrait"',
            'data-print-caption-mode="inline"',
            'data-print-caption-mode="separate"',
            'data-print-style="one"',
            'data-print-style="two"',
            'data-print-style="four"',
            'data-print-style="custom"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("竖版 · 上下双图", html)
        self.assertNotIn("横版 · 左右双图", html)
        self.assertIn("print-segment-group", css)
        self.assertIn('params.set("caption_mode"', js)
        self.assertIn('auto_fill: "1"', js)
        self.assertIn('caption_mode == "separate"', print_html)
        self.assertIn('class="page caption-sheet"', print_html)
        self.assertIn('caption_mode != "separate" and item.detail_rows', print_html)


class PrintLayoutGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import lazily and in an isolated data directory; this module is named
        # test_z_* so existing product tests establish their own environment first.
        cls.temp = tempfile.TemporaryDirectory(prefix="album-print-grid-")
        os.environ.setdefault("ALBUM_DATA_DIR", cls.temp.name)
        cls.appmod = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def photos(count):
        return [
            {
                "id": f"SYDY{index:03d}",
                "orientation": "landscape",
                "rotation": 0,
                "detail_rows": [
                    {"label": "题名", "value": "测试照片"},
                    {"label": "编号", "value": f"SYDY{index:03d}"},
                    {"label": "施工部位", "value": "测试单元"},
                    {"label": "拍摄时间", "value": "2026-09-09"},
                ],
            }
            for index in range(1, count + 1)
        ]

    def settings(self, caption_mode="inline"):
        return {
            "print_margin_top_mm": 6,
            "print_margin_right_mm": 6,
            "print_margin_bottom_mm": 6,
            "print_margin_left_mm": 6,
            "print_horizontal_gap_mm": 3,
            "print_vertical_gap_mm": 3,
            "print_caption_position": "bottom",
            "print_caption_mode": caption_mode,
            "print_caption_size_mm": 7.5,
            "print_show_page_title": True,
            "print_single_alignment": "center",
            "print_auto_fill": True,
        }

    def assert_inside_page(self, layout, page_size, items, settings):
        paper_w, paper_h = (210.0, 297.0) if layout == "portrait" else (297.0, 210.0)
        page_w = paper_w - settings["print_margin_left_mm"] - settings["print_margin_right_mm"]
        page_h = paper_h - settings["print_margin_top_mm"] - settings["print_margin_bottom_mm"] - 7.0
        for item in items:
            self.assertGreater(item["_photo_w"], 0)
            self.assertGreater(item["_h"], 0)
            self.assertGreaterEqual(item["_left"], -0.2)
            self.assertGreaterEqual(item["_top"], -0.2)
            self.assertLessEqual(item["_left"] + item["_w"], page_w + 0.6)
            self.assertLessEqual(item["_top"] + item["_block_h"], page_h + 0.6)

    def test_one_two_four_fit_both_landscape_and_portrait_with_inline_labels(self):
        for layout in ("landscape", "portrait"):
            for page_size in (1, 2, 4):
                settings = self.settings("inline")
                pages = self.appmod.layout_fixed_photo_pages(
                    self.photos(page_size), layout, page_size, 185, 123, settings
                )
                self.assertEqual(len(pages), 1)
                self.assertEqual(len(pages[0]), page_size)
                self.assert_inside_page(layout, page_size, pages[0], settings)
                self.assertTrue(all(item["_caption_h"] > 0 for item in pages[0]))

    def test_separate_caption_mode_gives_the_photo_the_whole_cell(self):
        for layout in ("landscape", "portrait"):
            settings = self.settings("separate")
            pages = self.appmod.layout_fixed_photo_pages(self.photos(2), layout, 2, 185, 123, settings)
            self.assertEqual(len(pages), 1)
            self.assertTrue(all(item["_caption_h"] == 0 for item in pages[0]))
            self.assert_inside_page(layout, 2, pages[0], settings)

    def test_custom_count_is_centered_by_cell_allocator_and_never_overflows(self):
        settings = self.settings("inline")
        pages = self.appmod.layout_fixed_photo_pages(self.photos(5), "portrait", 5, 260, 172, settings)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0]), 5)
        self.assert_inside_page("portrait", 5, pages[0], settings)
        # Different slots must occupy different fixed cells rather than piling up at top-left.
        positions = {(item["_left"], item["_top"]) for item in pages[0]}
        self.assertEqual(len(positions), 5)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

# Check edited source before fingerprint bump.
subprocess.run(["node", "--check", str(JS)], check=True)
# Official bump keeps JS/CSS/template/launcher/installer fingerprints in lockstep.
subprocess.run([sys.executable, "bump_version.py"], check=True)
# Check the renamed asset too.
new_js = next((ROOT / "assets").glob("app-A*.js"))
subprocess.run(["node", "--check", str(new_js)], check=True)
print("print-grid-autofill patch applied")
