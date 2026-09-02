"""Dependency-free repository secret scan used by CI and release checks."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_PATTERNS = (
    (
        "openai-api-key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    ),
    (
        "github-token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ),
    (
        "aws-access-key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)
_PLACEHOLDER_MARKERS = ("test", "example", "placeholder", "replace")


@dataclass(frozen=True, slots=True)
class Finding:
    path: Path
    line: int
    rule: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: potential {self.rule}"


def _is_placeholder(rule: str, matched_text: str) -> bool:
    if rule == "private-key":
        return False
    normalized = matched_text.casefold()
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def scan_paths(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > 1_000_000 or b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            allow_test_fixture = (
                "secret-scan: allow-test" in line
                and "tests" in {part.casefold() for part in path.parts}
            )
            for rule, pattern in _PATTERNS:
                for match in pattern.finditer(line):
                    if allow_test_fixture or _is_placeholder(rule, match.group(0)):
                        continue
                    findings.append(
                        Finding(path=path, line=line_number, rule=rule)
                    )
    return findings


def _repository_paths() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
    )
    return [Path(item) for item in result.stdout.decode("utf-8").split("\x00") if item]


def main() -> int:
    findings = scan_paths(_repository_paths())
    for finding in findings:
        print(finding.render())
    if findings:
        print(f"Secret scan failed with {len(findings)} finding(s).")
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
