# Progress

## Phase 0: Scaffold

### Built

- Added the `pyproject.toml` package metadata, Python 3.11+ requirement, runtime dependencies, and pytest configuration.
- Added `.env.example` with the documented runtime knobs plus YAML config paths.
- Added the `src/sdlc_agents` package and placeholder subpackages for tools, agents, metrics, and evaluation.
- Added `Settings` in `src/sdlc_agents/config.py` using `pydantic-settings` for `.env` loading and PyYAML for standards/pricing loading.
- Added placeholder project directories and entry points for the dashboard and baseline verifier.
- Added a Phase 0 import smoke test.
- Removed ignore rules that incorrectly excluded repository documentation, `.github`, and `WORKFLOW.md`.

### Decisions

- Used `pydantic-settings` rather than a dataclass because the project already requires Pydantic v2 and needs `.env` support.
- Kept YAML loading explicit through `Settings.standards`, `Settings.pricing`, and `Settings.load_yaml()`; environment variables remain the source for runtime knobs.
- Added one smoke test so `pytest` exits successfully instead of returning pytest's no-tests exit code.

### Verification

- Environment: Python 3.11.9 selected through pyenv. The default workspace interpreter remains Python 3.10.11, which does not satisfy the project requirement.
- `pip install -e ".[dev]"`: passed.
- `python -c "import sdlc_agents"`: passed.
- `Settings()` construction: passed.
- `python -m pytest`: passed, `1 passed`.

### Deviations

- The Phase 0 scaffold contains placeholder files only; toy-repo logic, schemas, deterministic tools, agents, graph routing, HITL, and hard gates remain deferred to their specified phases.
- Dependency versions are lower-bounded rather than pinned, so the install resolved current versions including LangChain 1.4.2 and LangGraph 1.2.12. Their phase-specific APIs must be verified before implementation.
- `config/standards.yaml` is an empty placeholder and `config/pricing.yaml` contains an empty model mapping until Phase 1.

### Next Steps

- Phase 1: implement the toy loan repository, standards/pricing configuration, tickets, ground truth, fixtures, and repository verification script.
- Review path scoping in `write_file`, `apply_hard_gates`, routing functions, and the HITL node when those phases are implemented.

## Phase 1: Toy Repo, Configs, Tickets, and Fixtures

### Built

- Implemented the `loan_repo/loan_calc` baseline with dataclasses, DTI calculation and bands, income verification, rate tiers, risk scoring, and eligibility evaluation.
- Added five baseline test files covering the loan modules and their boundary/error cases.
- Added the Phase 1 standards and pricing YAML configuration.
- Added tickets `T1` through `T8`, ground truth, design fixtures `D1`/`D2`/`D7`, and review fixtures `R1` through `R7`.
- Replaced `scripts/verify_repo.py` with a Pydantic ticket validator and isolated baseline/review-fixture verification.

### Decisions

- Kept the baseline logic intentionally small and deterministic so review signals are attributable to fixture changes.
- Used a local `Ticket` model in the Phase 1 verifier; the shared application schemas remain a Phase 2 deliverable.
- Kept the existing user change in `.env.example` (`MAX_TOOL_ITERATIONS=5`) unchanged.
- Used fresh temporary copies for every baseline and fixture check so the pristine toy repo is not mutated.

### Verification

- `python -m pytest`: passed, `1 passed` for the root framework suite.
- Baseline `loan_repo` tests: passed, `33 passed`, with 100% reported coverage.
- `python scripts/verify_repo.py`: passed, including ticket validation, baseline coverage thresholds, and review fixture signals.
- The verifier confirmed coverage-gap behavior for R2/R3, failing tests for R5, test tampering for R6, camelCase naming for R4, and the literal R7 mismatch fixture.

### Deviations

- The review fixture verifier checks deterministic fixture signals directly; the shared deterministic checks and LLM interpretation remain Phase 3 and later work.
- The project currently resolves unpinned dependencies, including Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.
- Existing tab indentation in the current standards and pricing YAML was invalid for PyYAML; it was normalized to spaces.

### Next Steps

- Phase 2: implement shared Pydantic schemas/state, the LLM client, and SQLite metrics storage.
- Review path scoping in `write_file`, `apply_hard_gates`, routing functions, and the HITL node when those phases are implemented.

## Phase 2: Schemas, State, LLM Client, and Metrics DB

### Built

- Added shared Pydantic v2 contracts in `src/sdlc_agents/schemas.py`, including ticket criteria validation, ambiguity-question consistency, and the three-question cap.
- Added `PipelineState` with typed agent results, HITL history accumulation, retry state, and pipeline outcomes.
- Added the injectable `LLMClient` protocol, `ChatModelClient`, provider-agnostic `get_llm()`, transient retry handling, and usage extraction.
- Added the `ScriptedLLM` offline test double in `tests/conftest.py`.
- Added SQLite metrics schema and helpers for runs, agent runs, HITL events, pricing, and correctness updates.
- Added `UsageTracker`, context-local tracking, pure token cost calculation, and the `tracked_node` decorator.
- Added focused Phase 2 tests for schema validation, usage/cost accounting, SQLite creation and persistence.

### Decisions

- `get_llm()` returns a small adapter that binds tools only when the caller supplies them, keeping the protocol usable by offline tests.
- Retry selection uses timeout types plus exception class names containing `ratelimit`, avoiding provider-specific imports while handling both configured providers.
- Metrics operations use one short-lived SQLite connection per operation, which keeps the prototype simple and avoids shared connection state.
- Zero or missing pricing resolves to a zero cost estimate, matching the configured pricing warning behavior planned for later reporting.

### Verification

- Installed API inspection confirmed `init_chat_model(model, model_provider=..., temperature=...)` in LangChain 1.4.2.
- Focused Phase 2 tests: passed, `5 passed`.
- Full `python -m pytest`: passed, `6 passed`.
- `python scripts/verify_repo.py`: passed.
- Diagnostics reported no errors in the touched Python files.

### Deviations

- LangChain 1.4.2 requires `total_tokens` in `AIMessage.usage_metadata`; the offline fixture includes it, while `extract_usage()` reads the required input/output fields.
- The project uses the installed unpinned versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12. No LangGraph runtime API was needed in Phase 2.
- Provider-specific rate-limit exception classes are not imported directly; class-name matching keeps the client provider-agnostic and will be revisited if runtime calls show a provider-specific mismatch.

### Next Steps

- Phase 3: implement and test deterministic repository tools, diffing, test execution, coverage, naming, and tampering checks.
- Review path scoping in `write_file`, `apply_hard_gates`, routing functions, and the HITL node when those phases are implemented.

## Phase 3: Deterministic Tools

### Built

- Added scoped `RepoTools` with Python-file listing, capped reads, regex search, AST-validated writes, and resolved-root path/symlink protection.
- Exposed repository operations as LangChain `StructuredTool` instances.
- Added deterministic unified diff generation with generated-artifact exclusions.
- Added bounded subprocess pytest execution with JUnit summary, first-five failures, coverage JSON parsing, and timeout handling.
- Added pure coverage, naming, test-tampering, and untested-public-function checks.
- Added focused tests for path escapes, absolute paths, symlink attempts, syntax rejection, diff behavior, coverage gaps, camelCase naming, deleted/reduced tests, and untested functions.

### Decisions

- Repository tools take `repo_root` at construction and never use a global repository path.
- `write_file` permits only relative `.py` paths, rejects traversal/absolute/symlink paths, caps content at 200 KB, and returns errors instead of raising into the agent loop.
- Naming checks accept explicit `(baseline_path, work_path)` pairs so only newly introduced AST names are evaluated.
- Test execution uses the current interpreter via `sys.executable`, a 60-second timeout, and `PYTHONDONTWRITEBYTECODE=1`.

### Verification

- Verified the installed `StructuredTool.from_function` factory signature before wrapping tools.
- Focused Phase 3 tests: passed, `11 passed, 1 skipped`.
- Full `python -m pytest`: passed, `17 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- Diagnostics reported no errors in the touched Phase 3 Python files.

### Deviations

- The symlink test is skipped when Windows cannot create symlinks in the current environment; the implementation still rejects symlink paths when present.
- The Phase 3 check APIs are implemented as pure utilities; agent integration and hard-gate behavior remain Phase 6 work.
- The project continues to use unpinned installed versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.

### Next Steps

- Phase 4: implement the shared tool loop and Design Agent with offline `ScriptedLLM` tests.
- Review `write_file` path scoping in the context of the Development Agent, then review `apply_hard_gates`, routing, and HITL when those phases are implemented.

## Phase 4: Shared Tool Loop and Design Agent

### Built

- Added `agents/base.py` with a bounded structured tool loop, assistant/tool message handling, terminal Pydantic validation, schema-retry feedback, tool-call tracking, and iteration-cap behavior.
- Added `SchemaRetriesExhausted` for persistent invalid terminal submissions.
- Added `agents/design_agent.py` with read-only repository tools, compact ticket/manifest/HITL input, `DesignDoc` terminal output, and affected-module/new-file validation.
- Added offline tests for the Design Agent happy path, invalid module retry, iteration-cap exhaustion, and non-terminal tool execution.

### Decisions

- Terminal schemas are converted to actual LangChain `StructuredTool` objects before being passed to `bind_tools`; terminal calls are intercepted and validated by the loop rather than executed as ordinary tools.
- Design-specific repository validation is supplied as a terminal validator so invalid module names consume schema retries and return actionable tool feedback.
- The loop accepts an explicit `max_schema_retries` value and the Design Agent reads it from `Settings`.
- Tool failures are returned as `ToolMessage` error text so the model can recover without exceptions escaping the loop.

### Verification

- Focused Phase 4 tests: passed, `4 passed`.
- Full `python -m pytest`: passed, `21 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- Diagnostics reported no errors in the touched Phase 4 files.

### Deviations

- The Phase 4 plan calls for manually running `cli design` on all eight tickets, but `cli.py` is a Phase 7 deliverable and no provider API key is configured in this environment. Offline tool-loop coverage is complete; the real-model/manual inspection remains pending CLI wiring and credentials.
- The requested later-phase high-risk areas (`apply_hard_gates`, routing, and HITL) are not implemented in Phase 4 and were not changed.
- The project continues to use unpinned installed versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.

### Next Steps

- Phase 5: implement the Development Agent, per-run working copies, write tooling integration, diff-derived results, and blocked/retry behavior.
- Revisit the real Design Agent run after CLI wiring exists; review `write_file` again in the Development Agent context, then review hard gates, routing, and HITL in their phases.

## Phase 5: Development Agent

### Built

- Added `agents/dev_agent.py` with per-run working-copy creation, read/write/search/list tool access, finish and blocked terminal models, and review-feedback/HITL context.
- Derived `files_changed` and the unified diff from baseline versus work-copy state rather than trusting model claims.
- Derived newly added `test_*` functions from AST comparison.
- Converted empty successful changes into `blocked` with `empty_diff` and iteration exhaustion into `blocked` with `iteration_cap`.
- Preserved the work copy for repeated calls with the same run ID so review retries continue from the current state.
- Added offline tests for success, blocked conflict reporting, empty-diff handling, cap handling, and work-copy reuse.

### Decisions

- Terminal tool identity is recorded in `UsageTracker.details` so the same shared loop can support `finish` and `report_blocked` without weakening the validated terminal contract.
- D7-style conflicts are represented as blocked results with a human-readable reason and no fabricated diff.
- `prepare_working_copy()` creates `runs/<run_id>/repo` only when absent; this makes retries stateful while keeping the baseline untouched.
- Development tools use the existing `RepoTools` path guard, so the agent cannot bypass Phase 3 write scoping.

### Verification

- Focused Phase 5 tests: passed, `5 passed`.
- Full `python -m pytest`: passed, `26 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- Explicit offline fixture check: D1, D2, and D7 each run three times; all 9 runs passed their expected outcome checks.
- Diagnostics reported no errors in the touched Phase 5 files.

### Deviations

- The first one-line fixture command had a shell parenthesis typo and did not execute; it was immediately rerun with a PowerShell here-string and passed. No source failure was involved.
- The real LLM/CLI execution remains unavailable because CLI wiring is a later phase and no provider API key is configured.
- The requested later-phase high-risk areas (`apply_hard_gates`, routing, and HITL) remain unchanged and deferred.
- The project continues to use unpinned installed versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.

### Next Steps

- Phase 6: implement Agent 3 review flow, deterministic hard gates, and review-fixture evaluation.
- Recheck `write_file` behavior through the Development Agent as changes expand, then review hard gates, routing, and HITL in their phases.

## Phase 6: Review Agent and Hard Gates

### Built

- Added `agents/review_agent.py` with deterministic test execution, coverage/naming/tampering/untested-function checks, compact review facts, and LLM review interpretation.
- Added pure `apply_hard_gates()` logic that merges code findings, rejects failing tests/coverage/error violations, and prevents risk from falling below the deterministic floor.
- Added deterministic `tests.failing` violations when the subprocess test summary reports failures.
- Added offline hard-gate and LLM design-mismatch tests.
- Ran all seven review fixtures three times on fresh copies with scripted LLM outputs.

### Decisions

- Deterministic facts are authoritative and are computed before the LLM call; the LLM can add findings but cannot override hard gates.
- Sensitive coverage gaps force high risk; non-sensitive coverage gaps force medium risk; error-severity violations force at least medium risk.
- Code findings and LLM findings are deduplicated by their serialized model content before returning the final `ReviewResult`.
- Corrected R3 and R6 fixture risk floors to `medium`, matching the Phase 6 gate contract for non-sensitive coverage and test-tampering errors.

### Verification

- Focused Phase 6 tests: passed, `5 passed`.
- Full `python -m pytest`: passed, `31 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- Review fixtures R1-R7: passed across 21 runs; R1 approved, R2-R6 rejected with expected deterministic rules, and R7 was rejected for the scripted `llm.design_mismatch`.
- Diagnostics reported no errors in the touched Phase 6 files.

### Deviations

- Review fixture evaluation was run through an offline here-string harness rather than a CLI command because CLI/evaluation wiring is scheduled for later phases.
- No provider API key was used; all Phase 6 checks were offline and used `ScriptedLLM`.
- The requested later-phase high-risk areas (routing and HITL) remain unchanged. `write_file` path scoping continues to be enforced through the existing `RepoTools` used by the Development Agent.
- The project continues to use unpinned installed versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.

### Next Steps

- Phase 7: wire the LangGraph pipeline, conditional routing, checkpointed HITL interrupts, CLI commands, and offline graph-path tests.
- Review routing functions and the HITL node directly when they are implemented; retain the existing write-path guard in the Development Agent.

## Phase 7: LangGraph Wiring, Routing, and HITL

### Built

- Added `graph.py` with ticket validation, Design/Development/Review nodes, pure conditional routing functions, finalization, and per-run `MemorySaver` checkpoints.
- Added a separate interrupt-only HITL node that records answers, rounds, blank-answer status, and optional SQLite HITL events before resuming the requesting agent.
- Added retry routing for rejected reviews, blocked development routing, unresolved HITL termination, and error termination.
- Added `SimulatedHuman` for deterministic scripted answers.
- Added basic `design` and `run` CLI commands using the same graph/LLM entry points.
- Added offline graph tests covering clean execution, design HITL/resume, unresolved HITL after two rounds, blocked development, retry then approve, exhausted retries, and error paths.

### Decisions

- Used `StateGraph(PipelineState)` with `MemorySaver`; each invocation uses `thread_id=run_id` so interrupt state is isolated per run.
- Kept routing functions pure and separate from node side effects, with final outcome assignment centralized in `finalize`.
- HITL resumes at the requesting agent and does not call an LLM inside the HITL node, avoiding duplicate agent calls on resume.
- Development retries reuse the existing per-run working copy and pass serialized review feedback back into the Development Agent.

### Verification

- Verified installed LangGraph 1.2.12 signatures for `StateGraph`, `MemorySaver`, `Command(resume=...)`, and `interrupt(value)`.
- Focused graph tests: passed, `7 passed`.
- Full `python -m pytest`: passed, `38 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- CLI smoke check: `python -m sdlc_agents.cli --help` passed and listed `design` and `run`.
- Diagnostics reported no errors in the touched Phase 7 files.

### Deviations

- The real `cli run T1` and interactive `cli run T5` checks could not be executed because no provider API key is configured; all graph paths were verified offline with `ScriptedLLM`.
- The CLI currently implements the Phase 7 `design` and `run` commands; evaluation subcommands remain Phase 8 work.
- The project continues to use unpinned installed versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.

### Next Steps

- Phase 8: implement isolated/e2e evaluation harnesses, scoring, SQLite batch updates, and evaluation reporting.
- Retain the existing `write_file` path guard and hard-gate behavior while expanding evaluation and CLI workflows.

## Phase 8: Evaluation Harness and Scoring

### Built

- Added pure scoring functions for Design, Development, Review, and pipeline outcomes, including module recall and expected-rule matching.
- Added offline isolated evaluation harnesses for all tickets/design fixtures/review fixtures with repeat support and SQLite run/agent correctness logging.
- Added an offline e2e smoke harness covering all eight tickets and declared pipeline outcomes.
- Added CLI commands `eval isolated --agent design|dev|review --repeats N`, `eval e2e --repeats N`, and `eval report`.
- Added Phase 8 scoring and persistence tests.

### Decisions

- Isolated evaluations execute the implemented agents with `ScriptedLLM`; no API key or nondeterministic provider call is required.
- Review fixture scoring treats expected rules as a subset requirement, allowing deterministic checks to report additional valid findings.
- Each evaluation inserts a `runs` row and an `agent_runs` row with `correct` populated, while e2e rows record the declared offline oracle outcome.
- The report groups SQLite rows by mode and counts correctness values for quick batch inspection.

### Verification

- Focused Phase 8 tests: passed, `2 passed`.
- `cli eval isolated --agent design --repeats 1`: passed, `8/8` correct.
- `cli eval isolated --agent dev --repeats 1`: passed, `3/3` correct.
- `cli eval isolated --agent review --repeats 1`: passed, `7/7` correct.
- `cli eval e2e --repeats 1`: passed, `8/8` correct.
- `cli eval report`: passed and reported grouped SQLite counts.
- Full `python -m pytest`: passed, `40 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- Final SQLite check showed `59` runs and `58` populated correctness values; the one incomplete row came from an intentionally failed exploratory command before the harness fix.

### Deviations

- The e2e harness uses the declared ground-truth outcomes as an offline oracle smoke mode; full LLM-driven e2e execution remains dependent on later prompt/evaluation integration and provider credentials.
- The persistent local `metrics.db` includes earlier exploratory rows from this phase, including one failed design attempt; successful evaluation rows have populated correctness.
- CLI evaluation commands currently use scripted offline execution rather than real provider calls.
- The project continues to use unpinned installed versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.

### Next Steps

- Phase 9: implement the Streamlit dashboard and metrics queries for latency, cost, accuracy, uncertainty surfacing, false positives, and success criteria.
- Keep `write_file` scoping, hard gates, routing, and HITL behavior covered while connecting the dashboard to real evaluation batches.

## Phase 9: Dashboard

### Built

- Added `metrics/queries.py` with filtered SQLite/DataFrame queries for latency, cost, accuracy, ticket pass rates, filter values, and success criteria.
- Replaced the dashboard placeholder with a Streamlit app containing batch/model/prompt/mode filters, empty-database messaging, latency box plot, stacked cost chart, accuracy KPIs, pass-rate table, and success-criteria table.
- Added focused dashboard aggregation tests using a temporary SQLite database.

### Decisions

- Kept SQL and aggregation logic in `metrics/queries.py` so `dashboard/app.py` remains a thin presentation layer.
- Used a database-path sidebar control with `metrics.db` as the default, which supports inspecting another evaluation database without changing code.
- Rendered empty query results as friendly informational states rather than failing figure/table creation.
- Kept the pass-rate display in `k/n` form per ticket, while preserving numeric aggregate columns for future dashboard filters.

### Verification

- Focused Phase 9 tests: passed, `1 passed`.
- Headless Streamlit smoke check: server started on port 8502 and `Invoke-WebRequest http://localhost:8502` returned HTTP 200.
- Full `python -m pytest`: passed, `41 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- Diagnostics reported no errors in the touched dashboard/query/test files.

### Deviations

- The dashboard currently includes the core three panels and required tables/checklist; stretch charts remain deferred.
- The displayed success criteria are compact database-backed checks rather than the full final evaluation report wording, which remains suitable for Phase 10 wrap-up refinement.
- The project continues to use unpinned installed versions: Python 3.11.9, pytest 9.1.1, LangChain 1.4.2, and LangGraph 1.2.12.

### Next Steps

- Phase 10: add the README with setup/run commands, architecture diagram, final results table, known limitations, and HITL explanation.
- Retain the existing path-scoping, hard-gate, routing, and HITL tests while documenting the completed system.

## Phase 10: Wrap-up

### Built

- Added `README.md` with Python setup, editable installation, environment configuration, test/verification commands, agent/graph/dashboard commands, and offline evaluation commands.
- Added Mermaid architecture and HITL sequence diagrams.
- Documented the final offline evaluation results: design 8/8, development 3/3, review 7/7, and e2e oracle smoke 8/8.
- Documented known limitations including provider credentials/cost, unpinned dependencies, timeout-only execution isolation, single toy repository scope, and deferred dashboard stretch panels.

### Decisions

- Documented both real-provider commands and scripted offline commands so the README reflects the two supported operating modes.
- Used the final successful Phase 8 batch figures in the results table rather than including exploratory failed rows from the local SQLite history.
- Kept the README focused on setup, operation, architecture, evaluation, and limitations; implementation details remain in the phase documentation.

### Verification

- README phase check: passed, all 11 required headings/commands/diagram markers present.
- Full `python -m pytest`: passed, `41 passed, 1 skipped`.
- `python scripts/verify_repo.py`: passed.
- Diagnostics reported no errors after the final documentation change.

### Deviations

- Phase 10 has no separate executable application check beyond README validation, the full test suite, and the existing repository verifier.
- The dashboard and real-provider commands are documented but require the environment/API credentials described in the README.

### Next Steps

- The planned phases are complete. Future work can pin dependencies, add dashboard stretch panels, run credentialed repeated evaluations, or replace the prototype toy-repo isolation with a stronger sandbox.

## Post-wrap-up Fix: Interactive T5 HITL

### Built

- Interactive CLI runs now use at least eight tool-loop iterations, allowing vague tickets such as T5 to reach the design submission that contains its blocking question even when `.env` sets the shared limit to five.

### Verification

- Focused graph/design tests: passed, `11 passed`.
- A credentialed T5 smoke attempt remained in the provider call without reaching a prompt before it was stopped; no provider output was available for confirmation.

## Post-wrap-up Fix: Dashboard Metrics

### Built

- Evaluation harnesses now load `config/pricing.yaml` into SQLite and record measured offline latency instead of hard-coded zero values.
- The dashboard cost message now distinguishes unavailable token usage from missing pricing.

### Verification

- Focused Phase 8 tests: passed, `3 passed`.
- Offline e2e rerun: batch `c46d2288f2f6`, all 8 tickets correct; latency recorded from `4.13 ms` to `6.04 ms` and one pricing row loaded.
- Offline scripted runs still have zero cost because they report zero input/output tokens; real-model runs are required for billable cost values.

