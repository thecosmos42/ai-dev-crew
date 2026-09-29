# Implementation Phases

Implement one phase at a time. Each phase ends with "Done when" checks. Do not start the next phase until they pass. See `DESIGN.md` for the overall design and `PROMPTS.md` for runtime prompts.

---

## Part 1: Locked-in decisions

| Item | Decision |
|---|---|
| Python | 3.11+, venv, `pyproject.toml` |
| Orchestration | `langgraph` (Pydantic state, conditional edges, `interrupt` + `Command(resume=...)`, `MemorySaver` checkpointer) |
| LLM access | `langchain` `init_chat_model`, provider-agnostic. Install `langchain-anthropic` and/or `langchain-openai`. Default to a cheap model while developing (e.g. `claude-haiku-4-5-20251001`), then run the final eval on a stronger one. |
| Schemas | Pydantic v2 |
| Testing | `pytest`, `pytest-cov` (toy repo and framework tests) |
| Storage | SQLite (`sqlite3` stdlib) |
| Dashboard | Streamlit, pandas, plotly |
| CLI | `typer`, `rich` |
| Retries | `tenacity` for API timeouts and rate limits |
| Config | YAML (`standards.yaml`, `pricing.yaml`), `.env` for secrets and knobs |

**Runtime knobs (`.env.example`):**
```
LLM_PROVIDER=anthropic
LLM_MODEL=claude-haiku-4-5-20251001
LLM_TEMPERATURE=0
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
SDLC_DB_PATH=metrics.db
PROMPT_VERSION=v1
MAX_TOOL_ITERATIONS=8
MAX_HITL_ROUNDS=2
MAX_SCHEMA_RETRIES=2
RUNS_DIR=runs
```

**Design principles the agent must follow:**
1. Code computes facts (diff, coverage, naming violations, module-name validity). The LLM interprets and decides.
2. All handoffs are validated Pydantic models. Human answers are the only free text.
3. Every agent takes an `LLMClient` object, so tests can inject a `ScriptedLLM` and run offline for free.
4. Each run works in a fresh temp copy of `loan_repo/`. The baseline is never mutated.
5. Because LLM-written code is executed, run pytest in a subprocess with a timeout. It's a prototype, so no sandbox beyond that.

---

## Part 2: File structure

```
sdlc-agents/
├── .github/
│   ├── copilot-instructions.md
│   └── prompts/                     # optional reusable phase prompts
├── docs/  DESIGN.md  PHASES.md  PROMPTS.md  COPILOT_WORKFLOW.md
├── PROGRESS.md
├── pyproject.toml   .env.example   .gitignore   README.md
├── config/
│   ├── standards.yaml
│   └── pricing.yaml
├── loan_repo/                       # pristine baseline toy repo (never mutated)
│   ├── pytest.ini                   # pythonpath = . ; testpaths = tests
│   ├── loan_calc/
│   │   ├── __init__.py  models.py  dti.py  income_verification.py
│   │   ├── rates.py  risk_scoring.py  eligibility.py
│   └── tests/
│       ├── conftest.py  test_dti.py  test_income_verification.py
│       ├── test_rates.py  test_risk_scoring.py  test_eligibility.py
├── data/
│   ├── tickets/T1.yaml … T8.yaml
│   ├── ground_truth.yaml
│   ├── design_fixtures/D1.yaml D2.yaml D7.yaml       # for isolated Agent 2
│   └── review_fixtures/R1.yaml … R7.yaml             # for isolated Agent 3
├── scripts/
│   └── verify_repo.py               # sanity-checks baseline + fixtures
├── src/sdlc_agents/
│   ├── __init__.py  config.py  llm.py  schemas.py  state.py  prompts.py
│   ├── tools/
│   │   ├── repo_tools.py            # list_files, read_file, write_file, search_code
│   │   ├── diffing.py               # difflib unified diff, baseline vs work copy
│   │   ├── test_runner.py           # run_tests()
│   │   └── checks.py                # coverage, naming, tampering, untested-function checks
│   ├── agents/
│   │   ├── base.py                  # shared tool loop
│   │   ├── design_agent.py  dev_agent.py  review_agent.py
│   ├── graph.py                     # nodes, routing, HITL node, build_graph()
│   ├── metrics/
│   │   ├── db.py                    # schema + helpers
│   │   ├── queries.py               # dashboard queries
│   │   └── tracker.py               # usage/latency capture + node decorator
│   ├── eval/
│   │   ├── simulated_human.py  harness.py  scoring.py
│   └── cli.py
├── dashboard/app.py
├── tests/                           # tests for the framework itself
│   ├── conftest.py                  # ScriptedLLM, tmp repo fixtures
│   ├── test_repo_tools.py  test_diffing.py  test_checks.py
│   ├── test_routing.py  test_metrics_db.py  test_scoring.py  test_graph_offline.py
└── runs/                            # gitignored temp repos, checkpoints
```

`.gitignore`: `.env`, `runs/`, `*.db`, `__pycache__/`, `.coverage`, `coverage.json`, `.venv/`.

---

## Part 3: Phases

### Phase 0: Scaffold
- Create the structure above (empty modules are fine), `pyproject.toml` with the dependencies in Part 1, `.env.example`, and `.gitignore`.
- Install in editable mode: `pip install -e ".[dev]"`.
- Add `.github/copilot-instructions.md` and `PROGRESS.md`.
- Create `src/sdlc_agents/config.py`, a `Settings` class (pydantic-settings or dataclass) that loads `.env` and YAML.

**Done when:** `python -c "import sdlc_agents"` works and `pytest` runs (0 tests is fine).

### Phase 1: Toy repo, configs, tickets, ground truth

**`loan_repo/loan_calc` specs** (small, readable, real logic):

- `models.py`: dataclasses `Applicant(applicant_id, age, monthly_income, monthly_debt_payments, credit_score, employment_months, employment_type, requested_amount, term_months, recent_delinquencies=0)` and `LoanDecision(approved, reasons: list[str], rate: float | None, risk_score: int)`.
- `dti.py`: `calculate_dti(monthly_debt, monthly_income) -> float` returns the **back-end DTI ratio** (0.35 means 35%) and raises `ValueError` if income ≤ 0. Also `dti_band(dti) -> str`. **Planted trap:** `calculate_dti` has three callers (`eligibility.evaluate`, `risk_scoring.score_applicant`, `rates.pick_rate`).
- `income_verification.py`: `verify_income(applicant) -> bool` (income > 0 and `employment_months >= 6`), `annualized_income(applicant)`.
- `rates.py`: constant `RATE_TIERS` (e.g. ≥740 → 0.060, 680–739 → 0.070, 620–679 → 0.085, 580–619 → 0.105), `pick_rate(applicant)` (calls `calculate_dti`, adds a 0.005 surcharge if DTI ≥ 0.36).
- `risk_scoring.py` (**sensitive**): `score_applicant(applicant) -> int` clamped 0–100 (credit score, DTI, and employment months components), `risk_bucket(score) -> str`.
- `eligibility.py` (**sensitive**): `evaluate(applicant) -> LoanDecision`. Rules: age ≥ 18, `MIN_CREDIT_SCORE=580`, `MAX_DTI=0.43`, income verified, risk score ≥ 50. It returns reason strings for declines.

**Baseline tests:** 5 test files, all passing. Target coverage: `risk_scoring.py` ≈ 95%, `eligibility.py` ≈ 90%, `rates.py` ≈ 90%, overall ≈ 85%. Add `pytest.ini` with `pythonpath = .` and `testpaths = tests`.

**`config/standards.yaml`:**
```yaml
naming:
  functions: {rule: snake_case, severity: error}
  classes: {rule: PascalCase, severity: error}
  constants: {rule: UPPER_SNAKE_CASE, severity: error}
  test_functions: {prefix: "test_", severity: error}
coverage:
  default_min: 75
  modules:
    loan_calc/risk_scoring.py: {min: 90, sensitive: true}
    loan_calc/eligibility.py:  {min: 85, sensitive: true}
    loan_calc/rates.py:        {min: 85, sensitive: false}
tests:
  forbid_deleting_existing_tests: true
  forbid_reducing_assertions: true
  require_test_for_new_public_functions: true
risk:
  sensitive_below_threshold: high
  non_sensitive_below_threshold: medium
  failing_tests: high
  naming_violation: medium
```

**`config/pricing.yaml`:** `models: {<model-name>: {input_per_1k: 0.0, output_per_1k: 0.0}}`. Fill in real prices from your provider. The code logs a warning when the price is 0.

**Tickets (`data/tickets/Tn.yaml`: id, title, description, acceptance_criteria):**

| ID | Title | Key acceptance criteria |
|---|---|---|
| T1 | Add excellent-credit rate tier | `pick_rate` returns 0.0525 for score ≥ 780 when DTI < 0.36; existing tiers unchanged; boundary tests at 779 and 780 |
| T2 | Longer history for self-employed | `self_employed` needs ≥ 24 months, others keep 6; failing applicants declined with reason `insufficient_employment_history`; unit tests |
| T3 | Recent delinquency penalty | `score_applicant` subtracts 15 if `recent_delinquencies >= 2`, 8 if 1; clamp 0–100 stays; **"Tests will be added in a follow-up ticket; do not add or modify files under tests/"** |
| T4 | Monthly payment estimator | Add `estimate_monthly_payment(principal, annual_rate, term_months)` to `rates.py` (amortization; `annual_rate == 0` → principal/term); **same "do not touch tests/" constraint** |
| T5 | Make eligibility stricter | "Eligibility should be stricter than today"; "Fewer risky applicants are approved" |
| T6 | Update maximum DTI policy | "Reject any applicant whose DTI exceeds 40%"; "Applicants with DTI up to 45% must continue to be approved when income is verified and credit score ≥ 620" |
| T7 | Front-end DTI definition | `calculate_dti` must keep that exact name and accept an `Applicant`; returns front-end DTI as a percentage using new field `monthly_housing_payment` (default 0.0); replace the existing implementation, no old function or alias |
| T8 | Add debt burden helper | Add public helper named exactly `computeDebtBurden(applicant)` in `dti.py` for parity with the API layer; returns debt/income, or 0.0 if income is 0; add tests in `tests/test_dti.py` |

The "do not touch tests/" text in T3 and T4 reliably plants coverage gaps end-to-end. The camelCase name in T8 reliably plants a naming violation. Agent 1 and Agent 2 don't see `standards.yaml`, so they follow the ticket.

**`data/ground_truth.yaml`** (per ticket):
```yaml
T1: {design: clean, dev: success, review: approve, pipeline: [approved], expected_modules: [loan_calc/rates.py], uncertainty_planted: null, max_dev_retries: 1, hitl_script: {}}
T2: {design: clean, dev: success, review: approve, pipeline: [approved], expected_modules: [loan_calc/income_verification.py, loan_calc/eligibility.py], uncertainty_planted: null, max_dev_retries: 1, hitl_script: {}}
T3: {design: clean, dev: success, review: reject, review_rules: [coverage.below_threshold], pipeline: [rejected], uncertainty_planted: null, max_dev_retries: 0, hitl_script: {}}
T4: {design: clean, dev: success, review: reject, review_rules: [coverage.below_threshold], pipeline: [rejected], uncertainty_planted: null, max_dev_retries: 0, hitl_script: {}}
T5: {design: flag_vague, dev: success, review: approve, pipeline: [approved], uncertainty_planted: design, max_dev_retries: 1,
     hitl_script: {design: ["Raise the minimum credit score from 580 to 620 and lower the maximum DTI from 0.43 to 0.40. No other rule changes."]}}
T6: {design: flag_contradictory, dev: success, review: approve, pipeline: [approved], uncertainty_planted: design, max_dev_retries: 1,
     hitl_script: {design: ["The 40% hard limit applies to everyone. Ignore the 45% criterion."]}}
T7: {design: any, dev: blocked, pipeline: [blocked, needs_human_unresolved], uncertainty_planted: dev, max_dev_retries: 1,
     hitl_script: {}}   # empty script => simulated human answers "I don't know"
T8: {design: clean, dev: success, review: reject, review_rules: [naming.function_snake_case], pipeline: [rejected, approved], uncertainty_planted: null, max_dev_retries: 1, hitl_script: {}}
```

**Design fixtures** (`D1`, `D2`, `D7`) are hand-written DesignDoc YAMLs for isolated Agent 2 runs. `D7` says "replace `calculate_dti` with a front-end version taking an Applicant" and lists only `dti.py` in `affected_modules` (the callers are not mentioned).

**Review fixtures** (`R1–R7`) are YAML with `id`, `design_ref`, `files: {relative_path: full_new_content}`, and `expected: {decision, rules, min_risk}`. They are applied to a fresh temp copy, then the diff is computed by code.

| ID | Scenario | Expected |
|---|---|---|
| R1 | Good T1 implementation with tests | approve |
| R2 | T3 implementation, no tests | reject, `coverage.below_threshold` on `risk_scoring.py`, risk high |
| R3 | T4 implementation, no tests | reject, `coverage.below_threshold` on `rates.py` |
| R4 | T8 with camelCase, tests included | reject, `naming.function_snake_case` |
| R5 | Changes `MIN_CREDIT_SCORE`, existing tests now fail | reject, `tests.failing` |
| R6 | T2 implementation plus deletes existing assertions | reject, `tests.tampering` |
| R7 | Tier value 0.0552 instead of 0.0525, with a test asserting 0.0552 | reject, `llm.design_mismatch` (only the LLM can catch this) |

**`scripts/verify_repo.py`:** copies the baseline to a temp dir, runs tests, and asserts they pass and coverage is close to the targets. Then it applies each review fixture and asserts the deterministic signals (R2 and R3 drop below thresholds, R5 fails tests, and so on).

**Done when:** `python scripts/verify_repo.py` passes and every YAML validates against the Pydantic `Ticket` model.

### Phase 2: Schemas, state, LLM client, metrics DB

**`schemas.py`:**
```python
class Ticket(BaseModel): id: str; title: str; description: str; acceptance_criteria: list[str]  # non-empty, non-blank, else ValueError
class OpenQuestion(BaseModel): question: str; why_blocking: str
class AmbiguityFlag(BaseModel): type: Literal["vague","contradictory","missing_dependency"]; detail: str
class DesignDoc(BaseModel):
    summary: str; affected_modules: list[str]; new_files: list[str] = []
    approach: str; edge_cases: list[str]; test_scenarios: list[str]
    assumptions: list[str] = []; open_questions: list[OpenQuestion] = []
    ambiguity_flags: list[AmbiguityFlag] = []; confidence: float = Field(ge=0, le=1)
    # validator: flags non-empty => open_questions non-empty; max 3 questions
class DevResult(BaseModel):
    status: Literal["success","blocked"]; files_changed: list[str] = []; tests_added: list[str] = []
    diff: str = ""; blocked_reason: str | None = None
    open_questions: list[OpenQuestion] = []; answerable_by_human: bool = False
    iteration_cap_hit: bool = False; notes: str = ""
class Violation(BaseModel): rule: str; file: str | None; detail: str; severity: Literal["error","warning"]; source: Literal["code","llm"]
class CoverageGap(BaseModel): file: str; required: float; actual: float; sensitive: bool
class TestSummary(BaseModel): passed: int; failed: int; total: int
class ReviewResult(BaseModel):
    risk_level: Literal["low","medium","high"]; violations: list[Violation]
    missing_coverage: list[CoverageGap]; test_summary: TestSummary
    approval_decision: Literal["approve","reject"]; rationale: str
    open_questions: list[OpenQuestion] = []; gate_overrides: list[str] = []
class HumanQA(BaseModel): agent: str; round: int; questions: list[OpenQuestion]; answer: str
PipelineOutcome = Literal["approved","rejected","blocked","needs_human_unresolved","error"]
```

**`state.py`:** `PipelineState(BaseModel)` with `run_id, ticket, repo_path, baseline_path, design, dev_result, review, review_feedback, human_qa (Annotated[list, operator.add]), pending_questions, pending_agent, hitl_rounds: dict[str,int], dev_attempts, max_dev_retries, pipeline_outcome, error`.

**`llm.py`:**
- `LLMClient` protocol with `invoke(messages, tools=None) -> AIMessage`.
- `get_llm()` returns a real implementation using `init_chat_model(model, model_provider=..., temperature=0)` with `bind_tools`, wrapped in `tenacity` (3 attempts, exponential backoff, on timeout and rate-limit errors).
- `extract_usage(ai_message) -> (tokens_in, tokens_out)` reads `usage_metadata`.
- `ScriptedLLM` in `tests/conftest.py` returns a queued list of `AIMessage`s (with `tool_calls`), so agents and graphs can be tested offline.

**`metrics/db.py`:** creates the tables below and provides `insert_run`, `update_run`, `insert_agent_run`, `update_correct`, `load_pricing`.
```sql
CREATE TABLE runs(run_id TEXT PRIMARY KEY, batch_id TEXT, ticket_id TEXT, mode TEXT,      -- 'isolated:design' | 'isolated:dev' | 'isolated:review' | 'e2e'
  repeat_index INT, model TEXT, prompt_version TEXT, started_at TEXT, ended_at TEXT,
  pipeline_outcome TEXT, pipeline_correct INT);
CREATE TABLE agent_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, agent TEXT, attempt INT,
  latency_ms INT, tokens_in INT, tokens_out INT, cost_estimate REAL,
  outcome TEXT,               -- pass | fail | blocked | flagged
  correct INT, schema_retries INT, tool_calls INT, hitl_rounds INT, hit_iteration_cap INT,
  uncertainty_planted INT, uncertainty_surfaced INT, confidence REAL, detail_json TEXT);
CREATE TABLE hitl_events(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, agent TEXT, round INT, n_questions INT, answer_blank INT);
CREATE TABLE pricing(model TEXT PRIMARY KEY, input_per_1k REAL, output_per_1k REAL);
```
Outcome mapping: design with open questions → `flagged`, else `pass`. Dev blocked → `blocked`, success → `pass`. Review reject → `flagged`, approve → `pass`. Any exception or exhausted schema retries → `fail`.

**`metrics/tracker.py`:** a `UsageTracker` (tokens, tool calls, schema retries, cap flag) held in a `contextvar`. `@tracked_node("design")` starts a timer and a fresh tracker, runs the node, computes cost from pricing, and inserts an `agent_runs` row. Latency covers node execution only (HITL wait time is excluded because the graph is paused). `attempt` = number of prior rows for `(run_id, agent)` + 1.

**Done when:** offline unit tests pass for schema validators (flags without questions rejected), DB creation, and cost calculation.

### Phase 3: Deterministic tools

**`repo_tools.py`** takes a `repo_root` at construction (not a global):
- `list_files()` returns relative POSIX paths of `.py` files (excluding `__pycache__`).
- `read_file(path)` errors if the file doesn't exist, and returns content with a 200 KB cap.
- `search_code(pattern)` is a plain regex/substring grep returning `path:line: text` (max 50 hits). It's a text search, not RAG.
- `write_file(path, content)` allows only relative `.py` paths. It rejects absolute paths, `..`, symlinks, and anything resolving outside `repo_root` (use `resolve()` + `is_relative_to`). Content must pass `ast.parse`, and on a syntax error it returns the error text to the model. Max 200 KB.
- Each function returns a string result or a clear error string (never raises into the LLM loop). Also expose them as LangChain `StructuredTool`s.

**`diffing.py`:** `make_diff(baseline, work) -> (diff_text, files_changed)` walks both trees (excluding `__pycache__`, `.coverage`, `coverage.json`, `*.xml`, `.pytest_cache`), builds a unified diff with `difflib`, and includes new and deleted files.

**`test_runner.py`:** `run_tests(repo_path) -> TestRunResult{summary, failures[:5], coverage: dict[file -> percent], raw_tail}`. It runs `[sys.executable, "-m", "pytest", "--cov=loan_calc", "--cov-report=json:coverage.json", "--junitxml=report.xml", "-q", "-p", "no:cacheprovider"]` with `cwd=repo_path`, a 60s timeout, and `PYTHONDONTWRITEBYTECODE=1`. It parses junit XML for counts and `coverage.json` for per-file `percent_covered`. Timeout counts as failed tests.

**`checks.py`** (all pure functions, fully unit-tested):
- `check_coverage(coverage, standards) -> (list[CoverageGap], list[Violation])`, using `rule="coverage.below_threshold"`.
- `check_naming(changed_py_files, standards)` uses AST: function names (snake_case), class names (PascalCase), module-level constants (UPPER_SNAKE). Only *newly added* names are flagged (diff against baseline AST). Rules: `naming.function_snake_case`, `naming.class_pascal_case`, `naming.constant_upper_snake`.
- `check_test_tampering(baseline, work)`: a deleted baseline test file, fewer test functions, or fewer `assert` statements in an existing test file gives `tests.tampering`. Newly added `pytest.skip`/`xfail` also counts.
- `check_untested_public_functions(baseline, work)`: a new public function whose name appears in no test file gives `tests.untested_public_function` (severity `warning`).

**Done when:** unit tests cover path-escape attempts (`../x`, `/etc/passwd`, symlink), diff correctness, coverage comparison, naming detection on a camelCase sample, and tampering detection.

### Phase 4: Shared tool loop and Agent 1 (Design)

**`agents/base.py` → `run_tool_loop(llm, system, user, tools, terminal_models, max_iters, tracker)`:**
1. Messages = system + user. Bind `tools + [terminal tools built from terminal_models]`.
2. Each iteration: invoke, add usage to tracker, execute non-terminal tool calls, and append `ToolMessage` results (count `tool_calls`).
3. If a terminal tool is called, validate its args with the Pydantic model. On `ValidationError` (or a custom validator error), return the error text as the `ToolMessage` and increment `schema_retries`. Beyond `MAX_SCHEMA_RETRIES`, raise `SchemaRetriesExhausted`.
4. If the model returns no tool call, append a nudge: "Call a tool. When finished, call the terminal tool."
5. On the final allowed iteration, append: "You must call the terminal tool now."
6. If the terminal tool is never called, return `None` and set `tracker.hit_cap = True`.

**`design_agent.py`:**
- Inputs: ticket, repo manifest (`list_files()` output), `human_qa`.
- Tools: `list_files`, `read_file`, `search_code`. Terminal: `submit_design` (schema = `DesignDoc`).
- Custom validation: every `affected_modules` entry must exist in the repo, and every `new_files` entry must not. A violation is returned as a schema error and counts toward retries.
- Stores `confidence` in the tracker for the calibration panel.

**Done when:** offline tests with `ScriptedLLM` cover the happy path, an invalid module name causing a retry, and cap exhaustion. Manually run Agent 1 on all 8 tickets (a `cli design T5` command) and inspect the output: T5 and T6 must flag, T1/T2/T3/T4/T8 must not.

### Phase 5: Agent 2 (Development)

- Per-run working copy via `shutil.copytree(loan_repo, RUNS_DIR/run_id/repo)`.
- Tools: `list_files`, `read_file`, `search_code`, `write_file`. Terminal tools: `finish(summary)` and `report_blocked(reason, open_questions, answerable_by_human)` (two terminal tools, so `run_tool_loop` accepts a set).
- After the loop, code does the following:
  - `finish` → `make_diff`, `files_changed` from the diff (not from the model), `tests_added` from AST (new `test_*` functions). An **empty diff with a success claim** becomes `blocked` with reason `empty_diff`.
  - `report_blocked` → `DevResult(status="blocked", …)`.
  - Cap hit → `blocked`, reason `iteration_cap`, `answerable_by_human=False`.
- On retry, `review_feedback` is included in the prompt. The working copy keeps its current state. The diff is always baseline vs work.

**Done when:** offline tests cover success, blocked, empty-diff, and cap paths. Run Agent 2 on `D1` and `D2` (must succeed with a non-empty diff) and `D7` (must return blocked with a reason naming the three callers). Confirm the D7 result on 3 repeats before moving on.

### Phase 6: Agent 3 (Review)

Flow inside the review node:
1. `run_tests` via the tool interface (logged as a tool call), then `check_coverage`, `check_naming`, `check_test_tampering`, and `check_untested_public_functions` in code.
2. Build a compact JSON "facts" block: test summary, coverage table with thresholds, code-found violations, the diff, and the design doc.
3. One LLM call with `read_file` available and terminal `submit_review` (`ReviewResult`). The LLM may add violations with `source="llm"` and rule names prefixed `llm.`.
4. **`apply_hard_gates(result, facts)`** (pure function, unit-tested):
   - failing tests → decision `reject`, risk `high`
   - any coverage gap → `reject`, risk `high` if sensitive else at least `medium`
   - any error-severity violation → `reject`, risk at least `medium`
   - The LLM can raise risk but never lower it below the gate floor.
   - Code-found violations and gaps are merged into the result (deduplicated), and any override is appended to `gate_overrides`.
5. The node returns the final `ReviewResult`.

**Done when:** offline tests for `apply_hard_gates`. Run Agent 3 on all 7 review fixtures ×3. R1 approves, R2–R6 reject with expected rules, and R7 is caught by the LLM.

### Phase 7: LangGraph wiring, routing, HITL

**Nodes:** `validate_ticket` → `design` → `hitl` → `dev` → `review` → `finalize`.
- Each agent node is wrapped with `@tracked_node` and a try/except that sets `pipeline_outcome="error"` on `SchemaRetriesExhausted` or a persistent API failure.
- On completion, each agent node clears `pending_questions`.
- Agent nodes that return open questions set `pending_questions` and `pending_agent`.

**HITL node (single-purpose, deliberately separate from the agents):** a resumed node re-executes from its top, so an LLM call inside it would be repeated. The node does this:
```python
if state.hitl_rounds.get(agent, 0) >= MAX_HITL_ROUNDS:
    return {"pipeline_outcome": "needs_human_unresolved"}
answer = interrupt({"agent": agent, "questions": [q.model_dump() ...], "round": n})
return {"human_qa": [HumanQA(...)], "hitl_rounds": {**rounds, agent: n+1}, "pending_questions": []}
```
Log a `hitl_events` row after the resume (blank or "I don't know" answers set `answer_blank=1`).

**Routing (pure functions in `graph.py`, unit-tested in `test_routing.py`):**
```
after_validate: invalid -> finalize(error) else design
after_design:   error -> finalize; design.open_questions -> hitl; else dev
after_hitl:     outcome set -> finalize; else pending_agent (design | dev | review)
after_dev:      error -> finalize
                blocked & answerable & rounds left -> hitl
                blocked -> finalize(blocked)
                success -> review
after_review:   error -> finalize
                review.open_questions & rounds left -> hitl
                approve -> finalize(approved)
                reject & dev_attempts < 1 + max_dev_retries -> dev (with review_feedback)
                reject -> finalize(rejected)
```
`finalize` sets the pipeline outcome if not already set and ends. `build_graph(llm, settings) -> CompiledGraph` uses `MemorySaver`; each run has its own `thread_id = run_id`.

**Driving the graph (same code in eval and interactive modes):**
```python
result = graph.invoke(initial_state, config)
while "__interrupt__" in result:
    answer = human.answer(result["__interrupt__"][0].value)   # SimulatedHuman or CLI prompt
    result = graph.invoke(Command(resume=answer), config)
```
LangGraph's API surface changes between versions. The agent must check the installed version's docs and signatures instead of assuming, and note any deviation in `PROGRESS.md`.

**`simulated_human.py`:** `SimulatedHuman(script)` returns `script[agent][round-1]` if present, else `"I don't know."`.

**CLI (`cli.py`):** `run T5 [--interactive]`, `design T5`, `eval isolated --agent design|dev|review --repeats 3`, `eval e2e --repeats 3`, `eval report`, `verify-repo`. Interactive mode prompts the terminal for answers.

**Done when:** offline `test_graph_offline.py` covers: clean path, design HITL then resume, unresolved HITL after 2 rounds, blocked dev, reject then retry then approve, reject with retries exhausted, and error path. Then run `cli run T1` with the real LLM and `cli run T5 --interactive`.

### Phase 8: Evaluation harness and scoring

**`harness.py`:** creates a `batch_id`, and for each (ticket or fixture, repeat) inserts a `runs` row, executes, logs, scores, and updates `correct`. Isolated modes:
- design: Agent 1 alone on all 8 tickets.
- dev: Agent 2 alone on `D1`, `D2`, `D7`.
- review: Agent 3 alone on `R1–R7`, applying fixture files to a fresh temp copy.

**`scoring.py` (pure functions, unit-tested):**
- **Agent 1** is scored on its first attempt only (before any human answer). `clean` → no flags and no questions. `flag_vague`/`flag_contradictory` → flag of that type and ≥ 1 question. Also compute `module_recall` against `expected_modules`.
- **Agent 2:** `success` → status success, non-empty diff, no deleted baseline test files. `blocked` → status blocked, empty diff, non-empty reason. If the pipeline stopped upstream, Agent 2 is marked "not reached" and excluded. For T7, upstream flagging by Agent 1 counts as uncertainty surfaced.
- **Agent 3 (fixtures):** correct if the decision matches, expected rules ⊆ reported rules, and for approve fixtures there are no error violations.
- **Agent 3 (end-to-end):** graded against code-computed oracle facts. It must reject if tests fail, coverage is below threshold, or an error violation exists. Extra LLM rejections on gate-clean diffs count toward false positives.
- **Pipeline correct:** `pipeline_outcome ∈ ground_truth.pipeline`.
- **Uncertainty-surfacing rate:** among runs with `uncertainty_planted`, the responsible agent's outcome was `flagged` or `blocked`.
- **False positive rate:** among clean tickets/fixtures, any flag, question, block, or reject that the oracle doesn't justify.
- **Confidence calibration:** bucket Agent 1's `confidence` (e.g. <0.5, 0.5–0.8, >0.8) and compute the correctness rate per bucket.
- **Success criteria report:** `cli eval report` prints pass/fail for each success criterion from `DESIGN.md` (Agent 3 ≥ 2/3 planted gaps, and so on).

**Done when:** `cli eval isolated` and `cli eval e2e --repeats 1` run cleanly, and rows appear in SQLite with `correct` populated.

### Phase 9: Dashboard (`dashboard/app.py`)
- Sidebar: filters for `batch_id`, `model`, `prompt_version`, `mode`. Show a friendly message when the DB is empty.
- **Panel 1:** latency by agent (plotly box plot from `agent_runs.latency_ms`).
- **Panel 2:** cost per ticket (stacked bar by agent, mean over repeats).
- **Panel 3:** accuracy metrics as KPI cards (per-agent correctness, uncertainty-surfacing rate, false positive rate), plus a per-ticket pass-rate table (repeats shown as `k/3`), plus a success-criteria checklist.
- Stretch: calibration chart, HITL rounds per ticket, pipeline outcome funnel, schema retries per agent.
- All queries live in `metrics/queries.py` so the dashboard stays thin.

**Done when:** `streamlit run dashboard/app.py` shows all panels from a real batch with no manual log-digging.

### Phase 10: Wrap-up
README with setup, run commands, architecture diagram (Mermaid), the results table from the last batch, known limitations, and a "how HITL works" section.

---

## Part 4: Edge case checklist

- Empty or malformed ticket: rejected in `validate_ticket` before Agent 1.
- Agent 1 invents module names: validator error, retry, then `error`.
- Flags without questions, or questions without `why_blocking`: schema error.
- Blank or "I don't know" answer: counts as a round, and the cap forces `needs_human_unresolved`.
- Human answer introduces a new conflict: Agent 1 may raise a new question, subject to the cap.
- Agent 2 writes outside the repo, writes invalid Python, loops, or claims success with an empty diff: handled as above.
- Agent 2 weakens existing tests: caught by `check_test_tampering`.
- Review LLM tries to approve despite failing gates: overridden and logged in `gate_overrides`.
- pytest hangs or crashes: 60s timeout, treated as failed tests.
- API timeout or rate limit: `tenacity` backoff, then `error`.
- Runs contaminate each other: per-run temp copy, baseline never touched.

---

## Part 5: Framework unit tests (must exist)

`test_repo_tools` (path escapes, syntax rejection), `test_diffing`, `test_checks`, `test_routing` (every routing branch), `test_metrics_db`, `test_scoring`, `test_graph_offline` (ScriptedLLM full graph paths). Rule: `pytest` in the repo root must pass offline with no API key.

---

## Part 6: Token-saving measures

**While building with Copilot**
- Fresh chat per phase, and read only that phase's section of this file.
- Keep `.github/copilot-instructions.md` short, since it loads on every request.

**At runtime**
- Enable provider prompt caching for the system prompts and repo manifest.
- Use a cheap model (Haiku-class) for development and prompt iteration; use a stronger one only for the final eval.
- Cap `read_file` output, return only matching lines from `search_code`, and give Agent 1 a manifest with one-line module summaries.
- Use `MAX_TOOL_ITERATIONS=5` for Agents 1 and 3 (keep 8 for Agent 2).
- Give Agent 3 only the changed hunks, a compact coverage table, and failures, not full pytest output.
- Send state as compact JSON (no indentation) and pass each agent only the fields it needs.

**During evaluation**
- Iterate with `--repeats 1`; run 3 repeats only for the final batch.
- Rerun only the agent whose prompt changed.
- Test everything offline with `ScriptedLLM` first (zero tokens).
