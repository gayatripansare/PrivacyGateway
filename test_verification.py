from pathlib import Path
from verification import verify_cleaned_file

root = Path('/tmp/privacygate_verify_test')
root.mkdir(exist_ok=True)
original = root / 'original.txt'
clean = root / 'clean.txt'
original.write_text('Email: person@example.com\nPhone: +91 98 7654 3210\n', encoding='utf-8')
clean.write_text('Email: [EMAIL]\nPhone: [PHONE]\n', encoding='utf-8')
findings = [
    {'type': 'EMAIL', 'value': 'person@example.com', 'risk': 'HIGH'},
    {'type': 'PHONE', 'value': '+91 98 7654 3210', 'risk': 'HIGH'},
]
verified = verify_cleaned_file(str(original), str(clean), findings)
assert verified['state'] == 'verified', verified
clean.write_text('Email: person@example.com\nPhone: [PHONE]\n', encoding='utf-8')
failed = verify_cleaned_file(str(original), str(clean), findings)
assert failed['state'] == 'failed', failed
print('verification regression passed')
