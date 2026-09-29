"""Subprocess pytest runner with bounded execution and coverage parsing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import TestSummary


@dataclass
class TestRunResult:
    summary: TestSummary
    failures: list[str] = field(default_factory=list)
    coverage: dict[str, float] = field(default_factory=dict)
    raw_tail: str = ""


def run_tests(repo_path: str | Path) -> TestRunResult:
    root = Path(repo_path)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--cov=loan_calc",
        "--cov-report=json:coverage.json",
        "--junitxml=report.xml",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return TestRunResult(TestSummary(passed=0, failed=1, total=1), ["pytest timed out"], output[-4000:])

    summary, failures = _parse_junit(root / "report.xml", completed.stdout + completed.stderr)
    coverage = _parse_coverage(root / "coverage.json")
    return TestRunResult(summary, failures[:5], coverage, (completed.stdout + completed.stderr)[-4000:])


def _parse_junit(path: Path, output: str) -> tuple[TestSummary, list[str]]:
    if not path.exists():
        failed = 1 if output else 0
        return TestSummary(passed=0, failed=failed, total=failed), [output[-1000:]] if failed else []
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return TestSummary(0, 1, 1), ["pytest produced no test suite"]
    total = int(suite.attrib.get("tests", 0))
    failures_count = int(suite.attrib.get("failures", 0)) + int(suite.attrib.get("errors", 0))
    skipped = int(suite.attrib.get("skipped", 0))
    failures: list[str] = []
    for testcase in suite.iter("testcase"):
        failure = testcase.find("failure")
        if failure is None:
            failure = testcase.find("error")
        if failure is not None:
            failures.append(f"{testcase.attrib.get('classname', '')}.{testcase.attrib.get('name', '')}: {failure.text or ''}")
    return TestSummary(passed=total - failures_count - skipped, failed=failures_count, total=total), failures


def _parse_coverage(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        Path(filename).as_posix(): float(details["summary"]["percent_covered"])
        for filename, details in data.get("files", {}).items()
    }