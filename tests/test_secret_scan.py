from pathlib import Path

from scripts.scan_secrets import scan_paths


def test_secret_scan_reports_location_without_echoing_secret(tmp_path: Path) -> None:
    secret = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"  # secret-scan: allow-test
    candidate = tmp_path / "config.py"
    candidate.write_text(f'API_KEY = "{secret}"\n', encoding="utf-8")

    findings = scan_paths([candidate])

    assert len(findings) == 1
    assert findings[0].rule == "openai-api-key"
    assert findings[0].path == candidate
    assert findings[0].line == 1
    assert secret not in findings[0].render()


def test_secret_scan_allows_explicit_test_placeholders(tmp_path: Path) -> None:
    candidate = tmp_path / "test_provider.py"
    candidate.write_text(
        'secret = "sk-test-secret-never-return"\n'
        'placeholder = "replace-with-your-key"\n',
        encoding="utf-8",
    )

    assert scan_paths([candidate]) == []
