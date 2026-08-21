from redactor.text_redactor import redact_text

cleaned, summary, restore = redact_text(
    'Email person@example.com',
    [{'type': 'EMAIL', 'value': 'person@example.com', 'replace': '[EMAIL]', 'risk': 'HIGH', 'start': 6, 'end': 24}],
)
assert '[EMAIL_1]' in cleaned
assert summary and restore
print('text redactor runtime passed')
