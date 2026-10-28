# Repeatable live demonstration

## Prepare

From the repository root, install dependencies and build the runner once:

```powershell
.\scripts\setup.ps1 -BuildRunner
docker info
docker image inspect rootcause-runner:local
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Set `RC_OLLAMA_MODEL` in `.env` to the exact installed Gemma tag if automatic
selection is unsuitable. A small local model can take time and can produce an
invalid patch; choose a model your machine can run reliably. Preload it before
presenting if startup latency matters. RootCause does not require cloud keys.

The inspected machine has no installed Ollama models and no Docker installation.
Complete these prerequisites before presenting the full repair flow. A suggested
model download command, supplied for the operator to run, is:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:4b
```

The tag is published by [Ollama](https://ollama.com/library/gemma3%3A4b). No model
download or sample-container test execution was performed during setup.

Start `scripts/start-backend.ps1` and `scripts/start-frontend.ps1` in two separate
PowerShell terminals. Open <http://127.0.0.1:5173>. Check infrastructure readiness
before importing. Keep both terminals open throughout the demonstration.

## Demonstrate a real repair

1. **Load the Order Service demo.** Use the dashboard's demo action. It copies
   the bundled sample into a new managed project. The source sample remains
   deliberately failing for the next run.
2. **Start an investigation.** Baseline tests run in the restricted Docker
   runner. This is the failure trigger: pytest executes the application
   functions and produces real assertions, exceptions, application logs, and
   stack traces. No pre-recorded trace is supplied.
3. **Inspect evidence.** Open baseline output and the source/configuration
   excerpts. The sample has API configuration, inventory-database, and order
   calculation behavior to investigate. The suite also contains passing
   checks that can reveal a regression. Several failures may share a cause.
4. **Follow the investigation.** Watch real phase events, diagnostics, ranked
   hypotheses, citations, and uncertainty. The model must explain the observed
   evidence. A model error or unsupported claim should remain visible.
5. **Review the proposed patch.** Inspect every changed file and line. Tests and
   protected setup files cannot be edited by the proposal. The patch exists as
   a reviewable diff before any source file is changed.
6. **Approve or reject.** Approval applies the reviewed source changes only to
   a separate candidate workspace, then triggers post-patch tests. Rejecting preserves
   the workspace. Do not approve a proposal solely to obtain a green screen.
7. **Inspect verification.** Compare the baseline and post-patch exit codes,
   pytest summaries, failures, and regressions. Claim a verified repair only
   when the recorded result is `verified`. This requires a failing baseline,
   the same unique test IDs before and after, at least one repaired failure,
   all post-patch tests passing, and no regression or missing test. If it fails,
   show the real output. A new investigation starts from the original imported
   source; prior candidates are not accumulated or promoted automatically.
8. **Open the report and history.** The report records observed evidence,
   hypotheses, patch review, test execution, and actual outcome. A partial or
   failed investigation is a valid report; it is not a verified fix.

Loading the bundled demo again creates a fresh copy. Never edit the checked-in
sample to reset an already repaired managed project. Model output varies, so a
single proposal is not guaranteed to repair every failure. RootCause contains
no prewritten success response or deterministic repair fallback.

## Optional independent baseline

To display the same actual failures before opening the dashboard, run the
read-only, offline Docker command from
[the sample README](../samples/order-service/README.md). This is optional: the
investigation automatically records its own baseline. A nonzero pytest exit
status is expected for the original sample, but read the output to distinguish
its intended failures from a broken Docker setup.

## Troubleshooting without hiding failures

| Observation | Action |
| --- | --- |
| Docker executable missing or daemon unreachable | Install/start Docker Desktop, enable Linux containers, then retry `docker info` |
| Runner image missing | Run `docker build -t rootcause-runner:local -f backend/runner/Dockerfile backend/runner` |
| Ollama unreachable | Confirm `RC_OLLAMA_URL`, start Ollama, and retry `/api/tags` |
| No local Gemma model | Inspect `ollama list`; install a suitable Gemma model and set its exact name |
| AI timeout or malformed response | Inspect the recorded error; use a suitable local model, increase `RC_AI_TIMEOUT` if needed, and start another investigation |
| Import rejected | Use a configured import root or validated ZIP; remove symlinks/junctions and unsupported content |
| Tests cannot import a dependency | Build a reviewed image containing that dependency; runtime package installation is intentionally disabled |
| Test timeout | Inspect test output, review test behavior, and adjust `RC_TEST_TIMEOUT` only when justified |
| Patch rejected as stale | Start another investigation so the diff is based on the current managed source |
| Post-patch tests fail | Preserve and show the output; a new investigation starts from unchanged imported source; do not describe the issue as resolved |
| Interrupted backend | Restart services; active work becomes `interrupted` and requires a new investigation; an existing proposal awaiting approval remains reviewable |

Do not replace missing evidence with invented output or execute the imported
sample on the host to work around Docker. Trusted backend tests and frontend
build commands are documented separately in the root README.
