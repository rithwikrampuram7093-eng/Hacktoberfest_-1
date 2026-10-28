# RootCause AI

An evidence-driven Python failure investigation and repair workbench. Import a
project, execute its tests in Docker, inspect source-linked AI hypotheses, review
a proposed patch, and explicitly approve a repair before running verification.
The application records actual test output and distinguishes a verified repair
from an unverified proposal or an unsuccessful fix.

The React dashboard connects to a local FastAPI service. SQLite stores projects,
investigations, evidence, events, proposed changes, and test results. Ollama is the
AI runtime; Codex and Claude Code are development tools and are not needed to run
the application. There is no cloud-model fallback or canned successful diagnosis.

On the inspected Windows machine (28 October 2026), Python 3.12 and Ollama were
already installed outside `PATH`; the local Ollama endpoint was reachable but
had no installed models, and Docker was absent. The Python virtual environment
and backend dependencies have been created. The full Docker/Gemma demonstration
has **not** been verified. See [the environment record](docs/environment.md).

## Windows setup

Prerequisites:

- Python 3.11 or newer. The setup script reuses `.venv`, then checks `PATH` and
  common per-user Python installation directories; no Python reinstallation is
  needed for this machine.
- Node.js 20.19+ or 22.12+ and `npm.cmd`.
- Docker Desktop running **Linux containers**. Its daemon must be reachable by
  your current Windows account.
- Ollama with a locally installed Gemma model for AI investigations. An Ollama
  installation or a model configured only in another coding assistant does not
  establish that the local Ollama HTTP API is available.

Open PowerShell in the repository root:

```powershell
.\scripts\setup.ps1 -BuildRunner
```

This creates `.venv`, installs the backend and frontend dependencies, creates
`.env` if absent, and builds `rootcause-runner:local`. Package installation and the
initial Docker image build require internet access. Subsequent project test runs
have networking disabled and install no dependencies.

To prepare the UI/API while Docker is unavailable, run `setup.ps1` without
`-BuildRunner`. The app can display intake, history, evidence, and honest degraded
health; it cannot verify imported tests without Docker. To choose an existing
Python installation explicitly:

```powershell
.\scripts\setup.ps1 -PythonPath "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

If PowerShell blocks scripts under your execution policy, use the direct commands
below or invoke a script with a process-scoped policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -BuildRunner
```

The equivalent direct setup commands are:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend install
Copy-Item .env.example .env
docker build -t rootcause-runner:local -f backend/runner/Dockerfile backend/runner
```

The direct `Copy-Item` command is for the first setup only; preserve your existing
`.env` when upgrading. Virtual-environment activation is unnecessary.

Inspect the local model connection:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

If Ollama is installed but stopped, run
`& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve` in a separate terminal.
For a suggested local model, [Ollama publishes the `gemma3:4b` tag](https://ollama.com/library/gemma3%3A4b).
Download it yourself when ready, then set `RC_OLLAMA_MODEL=gemma3:4b` in `.env`:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:4b
```

No model download was performed during development. Hardware needs and quality
vary by model size. Leaving `RC_OLLAMA_MODEL` empty enables detection of an
installed non-cloud Gemma model. If Ollama is on `PATH`, `ollama` can replace the
full executable path in these commands.

Start these services in **separate terminals**, each opened in this repository:

```powershell
# Terminal 1
.\scripts\start-backend.ps1
```

```powershell
# Terminal 2
.\scripts\start-frontend.ps1
```

Open <http://127.0.0.1:5173>. The backend listens on
<http://127.0.0.1:8000>; its interactive API reference is at
<http://127.0.0.1:8000/docs>. The frontend development server proxies `/api`
requests to the backend. Both services bind to the loopback interface.

Direct startup also loads the repository-root `.env`; process environment
variables take precedence:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## Try the live demonstration

1. Check the dashboard's Docker and Ollama readiness indicators.
2. Load the bundled Order Service demo. This copies `samples/order-service`
   into a managed workspace.
3. Start an investigation. Its baseline Docker test run triggers the real
   failures and captures evidence.
4. Follow the event stream, source-linked hypotheses, diagnostics, and patch.
5. Read the diff. Approve to apply the reviewed changes to a separate candidate and
   execute post-patch tests, or reject the proposal.
6. Read the before/after test output and report. A failed run, timeout, missing
   Docker daemon, or model error must remain visible as an incomplete outcome.

The sample has independent API/configuration, SQLite/data-processing, and order
calculation failures. It contains executable behavior tests, no prewritten
repair patch, and no fabricated log file. See [the repeatable demo procedure](docs/demo.md).

Every investigation starts from the imported project's unchanged source.
Approved candidates are retained separately under that investigation's data
directory; repairs are not promoted to the original project or accumulated
automatically across investigations.

## Import your own Python project

Use a local directory under `RC_IMPORT_ROOTS`, or upload a ZIP archive. The import
copies supported UTF-8 source/configuration/log files into the managed store and
does not run project code. Local-directory imports default to `./samples`; add
only directories that you intend the backend to read. Use absolute paths when
the projects live outside this repository. Existing `.env` files, common secret
files, databases, generated directories, links, and hidden files are excluded or
rejected. ZIP paths and expanded file sizes are validated.

Supply relevant error text with the investigation when available. A baseline
pytest execution also produces real failure evidence. The runner includes Python
and pytest, and supports projects whose test dependencies are already available
in that image. It never installs a project's `requirements.txt` during execution.
For additional dependencies, review them and build a separate runner image in
advance, then select it using `RC_DOCKER_IMAGE`.

## Configuration

The backend loads `.env` from the repository root using `python-dotenv`. Existing
process environment variables take precedence, including with direct `uvicorn`
startup. Paths are resolved from the backend's working directory;
the scripts consistently use the repository root.

| Variable | Default | Purpose |
| --- | --- | --- |
| `RC_OLLAMA_URL` | `http://127.0.0.1:11434` | Loopback HTTP Ollama API; remote/HTTPS URLs are rejected |
| `RC_OLLAMA_MODEL` | Empty | Exact installed model name, or Gemma auto-detection |
| `RC_DATA_DIR` | `./data` | SQLite database and isolated project workspaces |
| `RC_IMPORT_ROOTS` | `./samples` | Comma-separated allowlist for directory intake |
| `RC_DOCKER_IMAGE` | `rootcause-runner:local` | Prebuilt image for test execution |
| `RC_TEST_TIMEOUT` | `120` | Per-test-run timeout; 1–600 seconds |
| `RC_AI_TIMEOUT` | `180` | Per-AI-request timeout; 1–900 seconds |

Keep the backend local. It can read imported source and control Docker, and this
prototype has no account-based authorization or multi-user security layer. Do not
publish its port or expose it through a public tunnel.

## Checks

Run only the trusted backend test directory on the host:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
npm.cmd --prefix frontend run build
```

Run imported-project tests only through the Docker runner. See
[the sample README](samples/order-service/README.md) for a manual isolated command.
The root `pytest.ini` limits default collection to the trusted backend tests;
do not explicitly collect `samples/` or any imported-project directory on the host.

Real runtime integration is opt-in and requires Docker, the runner image, and a
local Gemma model. It checks actual baseline failures and a model-generated patch
proposal, while leaving approval to the developer:

```powershell
$env:RC_RUN_LIVE='1'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_live.py -q
Remove-Item Env:RC_RUN_LIVE
```

For a complete API-driven demo with a displayed diff and an interactive approval
prompt, start the backend and run:

```powershell
.\.venv\Scripts\python.exe scripts\review-demo.py
```

To serve the built frontend locally, use `npm.cmd --prefix frontend run preview`
and open <http://127.0.0.1:4173>. Both dev and preview servers proxy the local API.
See [the verification record](docs/verification.md) for executed checks and limits.

## Layout and boundaries

```text
backend/
  app/                 FastAPI, persistence, intake, evidence, AI and workflow
  runner/              Minimal offline pytest image
  tests/               Trusted backend and security tests
frontend/
  src/                 React dashboard and UI primitives
samples/order-service/ Executable failing app and behavioral tests
scripts/               Windows setup and service startup
docs/                  Architecture and live demo procedure
data/                  Runtime store (generated, not committed)
```

Imported Python is never imported or evaluated by the backend. Test execution
uses a non-root Docker container with disabled network, a read-only project
mount/root filesystem, bounded temporary storage, dropped capabilities, process
limits, memory/CPU limits, and a timeout. The AI cannot supply shell commands.
Patch validation protects tests and executable setup configuration, requires
exact source matches and unchanged base hashes, and confines edits to existing
application source/configuration in the managed copy. Each run copies a read-only
snapshot into temporary container storage, so projects can create scratch files
without writing back to the host project.

This is a local hackathon application, not a hardened hostile-code hosting
service. Docker shares a kernel with its host VM; isolation is not a security
proof. Text redaction covers common credential patterns, not every possible
secret. Review the imported files before analysis. Remote/cloud Ollama endpoints
are rejected. Verification requires a failing baseline followed by a fully
passing suite with the same unique test IDs, at least one fixed failure, and no
lost or regressed test. It does not prove that all possible bugs are fixed.
Persistent records survive a restart, but active work is marked `interrupted`
and is not resumed automatically; proposals awaiting approval remain reviewable.
Use one backend instance.

See [architecture and security decisions](docs/architecture.md) and
[the API reference](docs/api.md) for details.
