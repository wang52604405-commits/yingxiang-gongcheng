from pathlib import Path

path = Path('tests/test_mobile_server.py')
text = path.read_text(encoding='utf-8')
old = 'self.assertEqual(own_payload["upload_quota"]["remaining"], 100)'
new = 'self.assertEqual(own_payload["upload_quota"]["remaining"], 500)'
if text.count(old) != 1:
    raise SystemExit(f'expected exactly one stale quota assertion, found {text.count(old)}')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('quota assertion updated to 500')
