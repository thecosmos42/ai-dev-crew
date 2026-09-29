"""Verify the Phase 1 toy repository and review fixtures."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "loan_repo"
TICKETS = ROOT / "data" / "tickets"
REVIEW_FIXTURES = ROOT / "data" / "review_fixtures"


class Ticket(BaseModel):
	id: str
	title: str
	description: str
	acceptance_criteria: list[str]

	@field_validator("acceptance_criteria")
	@classmethod
	def criteria_must_be_nonempty(cls, values: list[str]) -> list[str]:
		if not values or any(not criterion.strip() for criterion in values):
			raise ValueError("acceptance_criteria must contain non-blank values")
		return values


def load_yaml(path: Path) -> dict[str, Any]:
	with path.open(encoding="utf-8") as yaml_file:
		value = yaml.safe_load(yaml_file)
	if not isinstance(value, dict):
		raise AssertionError(f"Expected mapping in {path}")
	return value


def run_tests(repo_path: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, float]]:
	environment = os.environ.copy()
	environment["PYTHONDONTWRITEBYTECODE"] = "1"
	result = subprocess.run(
		[
			sys.executable,
			"-m",
			"pytest",
			"--cov=loan_calc",
			"--cov-report=json:coverage.json",
			"-q",
			"-p",
			"no:cacheprovider",
		],
		cwd=repo_path,
		env=environment,
		capture_output=True,
		text=True,
		timeout=60,
	)
	coverage_path = repo_path / "coverage.json"
	coverage = {}
	if coverage_path.exists():
		raw = json.loads(coverage_path.read_text(encoding="utf-8"))
		coverage = {
			Path(path).as_posix(): data["summary"]["percent_covered"]
			for path, data in raw.get("files", {}).items()
		}
	return result, coverage


def apply_fixture(fixture: dict[str, Any], target: Path) -> None:
	for relative_path, content in fixture["files"].items():
		destination = target / relative_path
		destination.parent.mkdir(parents=True, exist_ok=True)
		destination.write_text(content, encoding="utf-8")


def count_assertions(path: Path) -> int:
	tree = ast.parse(path.read_text(encoding="utf-8"))
	return sum(isinstance(node, ast.Assert) for node in ast.walk(tree))


def has_camel_case_function(path: Path) -> bool:
	tree = ast.parse(path.read_text(encoding="utf-8"))
	return any(
		isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
		and any(character.isupper() for character in node.name)
		for node in ast.walk(tree)
	)


def validate_tickets() -> None:
	ticket_paths = sorted(TICKETS.glob("T*.yaml"))
	assert [path.stem for path in ticket_paths] == [f"T{index}" for index in range(1, 9)]
	for path in ticket_paths:
		ticket = Ticket.model_validate(load_yaml(path))
		assert ticket.id == path.stem


def validate_baseline() -> None:
	with tempfile.TemporaryDirectory() as temporary_directory:
		target = Path(temporary_directory) / "loan_repo"
		shutil.copytree(BASELINE, target)
		result, coverage = run_tests(target)
		assert result.returncode == 0, result.stdout + result.stderr
		assert coverage.get("loan_calc/risk_scoring.py", 0) >= 90
		assert coverage.get("loan_calc/eligibility.py", 0) >= 85
		assert coverage.get("loan_calc/rates.py", 0) >= 85
		assert sum(coverage.values()) / len(coverage) >= 85


def validate_review_fixtures() -> None:
	standards = load_yaml(ROOT / "config" / "standards.yaml")
	assert standards["coverage"]["modules"]["loan_calc/risk_scoring.py"]["sensitive"]
	assert load_yaml(ROOT / "config" / "pricing.yaml")["models"]
	baseline_test = BASELINE / "tests" / "test_income_verification.py"
	baseline_assertions = count_assertions(baseline_test)

	for fixture_path in sorted(REVIEW_FIXTURES.glob("R*.yaml")):
		fixture = load_yaml(fixture_path)
		expected = fixture["expected"]
		assert {"id", "design_ref", "files", "expected"} <= fixture.keys()
		assert expected["decision"] in {"approve", "reject"}
		with tempfile.TemporaryDirectory() as temporary_directory:
			target = Path(temporary_directory) / "loan_repo"
			shutil.copytree(BASELINE, target)
			apply_fixture(fixture, target)
			fixture_id = fixture["id"]
			if fixture_id == "R2":
				result, coverage = run_tests(target)
				assert result.returncode == 0, result.stdout + result.stderr
				assert coverage.get("loan_calc/risk_scoring.py", 100) < 90
			elif fixture_id == "R3":
				result, coverage = run_tests(target)
				assert result.returncode == 0, result.stdout + result.stderr
				assert coverage.get("loan_calc/rates.py", 100) < 85
			elif fixture_id == "R5":
				result, _ = run_tests(target)
				assert result.returncode != 0
			elif fixture_id == "R6":
				assert count_assertions(target / "tests" / "test_income_verification.py") < baseline_assertions
			elif fixture_id == "R4":
				assert has_camel_case_function(target / "loan_calc" / "dti.py")
			elif fixture_id == "R7":
				assert "0.0552" in fixture["files"]["loan_calc/rates.py"]


def main() -> None:
	validate_tickets()
	validate_baseline()
	validate_review_fixtures()
	print("Phase 1 repository verification passed")


if __name__ == "__main__":
	main()
