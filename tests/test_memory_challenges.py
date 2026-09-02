import subprocess
import sys
from io import StringIO
from pathlib import Path

from scripts.run_memory_challenges import load_cases, run_challenges

CHALLENGE_PATH = Path(__file__).parents[1] / "evaluation" / "memory_challenges.json"


def test_checked_in_challenges_cover_the_agreed_memory_behaviors() -> None:
    cases = load_cases(CHALLENGE_PATH)

    assert {case.category for case in cases} >= {
        "abstention",
        "alias-coreference",
        "chinese",
        "explicit-fact",
        "memory-governance",
        "multi-hop",
        "option-assisted",
        "preference",
        "procedure",
        "security",
        "temporal-normalization",
        "temporal-update",
    }
    assert all(case.required_excerpts or case.expect_empty for case in cases)
    assert any(case.forbidden_excerpts for case in cases)


def test_challenge_runner_shows_evidence_and_non_official_diagnostics() -> None:
    output = StringIO()

    passed = run_challenges(load_cases(CHALLENGE_PATH), output=output)

    rendered = output.getvalue()
    assert passed is True
    assert "FOUND" in rendered
    assert "All challenge expectations were visible." in rendered
    assert "Local diagnostics (not an official leaderboard score)" in rendered
    assert "Recall@K" in rendered
    assert "MRR" in rendered
    assert "nDCG" in rendered
    assert "Noise rate" in rendered
    assert "Abstention accuracy" in rendered


def test_command_line_output_is_utf8_and_keeps_chinese_readable() -> None:
    script = Path(__file__).parents[1] / "scripts" / "run_memory_challenges.py"

    completed = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    rendered = completed.stdout.decode("utf-8")
    assert "我现在周末去哪里跑步？" in rendered  # noqa: RUF001
    assert "新的跑步地点：玄武湖。那里更安静。" in rendered  # noqa: RUF001
