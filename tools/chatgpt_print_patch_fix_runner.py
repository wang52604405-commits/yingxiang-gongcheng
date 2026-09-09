# -*- coding: utf-8 -*-
from pathlib import Path
import subprocess
import sys

path = Path("tools/chatgpt_print_patch_20260909.py")
text = path.read_text(encoding="utf-8")
old_end = "}\n\n\ndef print_layout_from_request'''"
new_end = "}'''"
if old_end not in text:
    raise SystemExit("style replacement terminator not found")
text = text.replace(old_end, new_end, 1)
old_call = '''    r'PRINT_STYLE_DEFAULTS = \\{.*?\\n\\}\\n\\n\\ndef print_layout_from_request',
    style_defaults,
    "print style defaults",
)'''
new_call = '''    r'PRINT_STYLE_DEFAULTS = \\{.*?\\n\\}\\n\\n\\ndef print_settings_from_request',
    style_defaults + "\\n\\n\\ndef print_settings_from_request",
    "print style defaults",
)'''
if old_call not in text:
    raise SystemExit("style regex call not found")
text = text.replace(old_call, new_call, 1)
path.write_text(text, encoding="utf-8")
subprocess.run([sys.executable, str(path)], check=True)
