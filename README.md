# RootCause AI

A local Python failure investigation and repair workbench with evidence, reviewable
patches, explicit approval, real test execution, and persistent history.

**Demo Mode** runs three bundled failure scenarios with clearly labeled,
preconfigured analysis. **Live AI** investigates projects using a local Ollama
model and Docker. The modes are selected explicitly; a missing model never
silently becomes a predefined diagnosis.

## Run the model-free demo on Windows

The development workspace already has its Python environment and dependencies.
For a clean clone, install Python 3.11+ and Node.js with `npm.cmd`, then prepare
dependencies once, without building a Docker image:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Open two PowerShell terminals in the repository root:

```powershell
# Terminal 1: explicitly allow local execution of the three trusted demos.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1 -EnableTrustedDemoRunner
```

```powershell
# Terminal 2
npm.cmd --prefix frontend run dev
```

Open <http://127.0.0.1:5173>. Select **Demo Mode**, choose a scenario, and select
**Start demo**. Inspect the reproduced failure, collected evidence, predefined
hypotheses, and proposed diff. Approve the displayed patch to run verification
in a separate candidate copy. **Reset Demo** starts a fresh failing investigation
and keeps the previous run in history.

| Scenario | Reproduced failure | Observed baseline → candidate |
| --- | --- | --- |
| `api-config` | Configuration lookup uses the wrong API URL key | 4 passed, 1 failed → 5 passed |
| `database-query` | SQLite query selects a nonexistent column | 2 passed, 3 failed → 5 passed |
| `logical-total` | Order total omits item quantities | 4 passed, 1 failed → 5 passed |

Demo conclusions and repairs are predefined teaching material, labeled
**Demo Investigation — Preconfigured AI Analysis**. Source collection, diagnostics,
logs, exit codes, and before/after tests come from actual execution. A successful
test result is never substituted for an unavailable or failed run. All three
scenario flows have been exercised through the API with real failing baselines,
approval, five passing candidate tests each, and a fresh failure after reset.
See [the verification record](docs/verification.md) for current results and limits.

The opt-in runner executes only complete, hash-pinned shipped baselines or their
exact deterministic repair candidates. It validates every file and directory,
rejects changed tests, extra files, links, and arbitrary patches, then executes
trusted definition bytes in a fresh temporary directory. It uses the **host
Python interpreter**, not Docker isolation. Its child receives a minimal
environment; Windows process jobs enforce process/memory limits and terminate
descendants on timeout. Imported projects and Live AI patches always require
Docker. The local exception is disabled by default.

For a short presentation script, see [the 90-second demo procedure](docs/demo.md).

## Set up Live AI and Docker

Live AI needs Docker Desktop running Linux containers, a locally built runner
image, and an installed Ollama model. Codex and Claude Code are development tools;
neither is an application runtime dependency.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -BuildRunner
```

The setup script reuses `.venv`, or checks existing Python installations on
`PATH` and under `%LOCALAPPDATA%\Programs\Python`. It installs the backend and
frontend dependencies, creates `.env` only if absent, and builds the runner when
`-BuildRunner` is supplied. Dependency installation and image building need
internet access. Docker test runs install no project dependencies and disable networking.
An existing Python installation can be selected explicitly:

```powershell
.\scripts\setup.ps1 -PythonPath "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -BuildRunner
```

Inspect the actual local Ollama connection:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

If Ollama is stopped, launch `ollama serve` using its installed executable.
Select an installed non-cloud model with `RC_OLLAMA_MODEL` in `.env`; an empty
value auto-detects a locally installed Gemma model. A model configured only in
another coding assistant is not evidence that Ollama can serve it. No model was
downloaded during development.

Start the backend without the demo opt-in flag and run the frontend in another
terminal. The API is at <http://127.0.0.1:8000>, with interactive documentation at
<http://127.0.0.1:8000/docs>:

```powershell
.\scripts\start-backend.ps1
```

```powershell
npm.cmd --prefix frontend run dev
```

Direct backend startup also loads the repository-root `.env`; process environment
variables take precedence:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Select **Live AI**, import a project, and supply relevant error text. The backend
collects evidence, runs a Docker baseline, requests evidence-cited hypotheses
and minimal edits from Ollama, and waits for explicit patch approval. Missing
Docker or model requirements remain visible. A blocked Live AI run stays in
history; selecting a demo creates a separate investigation.

On the inspected Windows machine, Python 3.12 and Ollama were already installed
outside `PATH`; Ollama returned an empty model inventory, and Docker was absent.
The real model-generated Docker repair flow remains unverified. The model-free
demo has been executed locally with the explicit trusted-runner exception.
See [environment details](docs/environment.md).

## Import your own Python project

Directory imports must stay inside `RC_IMPORT_ROOTS`; ZIP uploads are validated
before copying supported UTF-8 source, configuration, and log files. Intake does
not execute project code. Hidden files, common secret files, databases, generated
directories, symbolic links, junctions, traversal paths, and oversized inputs are
excluded or rejected. Only allow directory roots you intend the backend to read.

Imported code executes exclusively in the restricted Docker runner. The image
contains Python and pytest; it never installs `requirements.txt` at test time.
Review additional dependencies and build a separate image in advance when needed,
then select it with `RC_DOCKER_IMAGE`. `samples/order-service` remains an additional
failing project for the Docker/Live AI path.

Each investigation preserves its source baseline. Approval applies reviewed edits
to a separate candidate. Candidates are never automatically promoted to imported
projects, and a new investigation starts from unchanged imported source.

## Configuration

The backend loads `.env` from the repository root. The startup scripts use that
directory consistently; process environment variables take precedence.

| Variable | Default | Purpose |
| --- | --- | --- |
| `RC_OLLAMA_URL` | `http://127.0.0.1:11434` | Loopback HTTP Ollama endpoint; remote endpoints and credentials are rejected |
| `RC_OLLAMA_MODEL` | Empty | Exact installed non-cloud model name, or local Gemma detection |
| `RC_DATA_DIR` | `./data` | SQLite database and managed workspaces |
| `RC_IMPORT_ROOTS` | `./samples` | Comma-separated directory intake allowlist |
| `RC_DOCKER_IMAGE` | `rootcause-runner:local` | Prebuilt project-test image |
| `RC_TEST_TIMEOUT` | `120` | Docker run timeout, 1–600 seconds; trusted demos use at most 30 seconds |
| `RC_AI_TIMEOUT` | `180` | Per-request AI timeout, 1–900 seconds |
| `RC_ENABLE_TRUSTED_DEMO_RUNNER` | `false` | Explicit local execution permission for exact bundled demos only |

Docker is preferred for demo execution when available. Otherwise the trusted
runner is eligible only when enabled, in Demo Mode, for a manifest-verified
scenario. Verification uses the same runner as the baseline. Health can remain
`degraded` for Live AI while `demo.execution_available` is true.

SQLite upgrades add the mode/scenario metadata columns without deleting existing
history. Older records remain Live AI records. Active work is marked
`interrupted` after a restart; pending approval proposals remain reviewable.

## Checks and execution boundaries

Run the trusted backend tests and frontend build:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
npm.cmd --prefix frontend run build
```

The trusted backend suite includes explicit tests of the hash-pinned local demo
exception. Do not directly collect `samples/` or an imported project's tests on
the host. Root pytest configuration limits default collection to backend tests.
Run imported-project tests through Docker.

The optional real-model/Docker integration test requires both runtimes:

```powershell
$env:RC_RUN_LIVE='1'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_live.py -q
Remove-Item Env:RC_RUN_LIVE
```

For a terminal review flow with an explicit approval prompt, start the backend
with the demo flag and run:

```powershell
.\.venv\Scripts\python.exe scripts\review-demo.py --mode demo --scenario api-config
```

Choose `database-query` or `logical-total` for the other cases. `--mode live`
requires Docker and the configured Ollama model.

`npm.cmd --prefix frontend run preview` serves the built UI on
<http://127.0.0.1:4173> and proxies the local API. Browser visual verification and
live runtime checks are reported separately in [verification.md](docs/verification.md).

## Layout and limits

```text
backend/app/              FastAPI, persistence, providers, workflow and runners
backend/runner/           Restricted Docker pytest image
backend/tests/            Trusted application and security tests
frontend/src/             React dashboard and UI primitives
samples/demo-scenarios/   Three immutable bundled demonstration projects
samples/order-service/    Additional failing project for Docker/Live AI
scripts/                  Windows setup and service startup
docs/                     API, architecture, demo and verification records
data/                     Generated SQLite store and managed workspaces
```

Docker tests use a non-root user, disabled network, read-only project/root mounts,
bounded temporary storage, dropped capabilities, resource limits, and a timeout.
The model cannot issue shell commands. Patches require existing allowed paths,
exact matches, valid candidate syntax, unchanged base hashes, and explicit
approval. Tests, configured pytest test paths/patterns, dependency/setup files,
hidden files, and secrets are protected. Windows CRLF and UTF-8 BOM content are
preserved during supported edits.

A verified repair requires a failing baseline, an entirely passing candidate,
the same unique test IDs and runner, at least one fixed failure, and no missing
or regressed tests. Project-provided assertions and reports are debugging
evidence; they cannot attest correctness of hostile code or every possible input.
Credential redaction is heuristic. Keep the service on loopback, use one backend
instance, and protect the data directory. There is no account system or public
hosting security layer.

See [architecture](docs/architecture.md) and [the API reference](docs/api.md).
