# Development environment

Recorded on **28 October 2026**, using the user's India time context. This is an
inspection and execution record; use `/api/health` for current runtime readiness.

| Component | Observed state |
| --- | --- |
| Workspace | `C:\Users\Admin\Downloads\HCK` |
| Python | Existing Python 3.12 at `C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe`, outside the session's `PATH` |
| Backend | Repository `.venv` created from the existing installation; dependencies installed |
| Ollama executable | Existing `C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe`, outside `PATH` |
| Ollama API | `http://127.0.0.1:11434/api/tags` reachable with `models: []` |
| Local Gemma | No installed model in the inspected inventory |
| Docker | CLI/runtime unavailable in the inspected environment |
| Trusted local demos | API: 4 passed/1 failed; SQLite: 2 passed/3 failed; logic: 4 passed/1 failed. Each approved candidate passed all five tests |
| API demo flows | All three exercised through the running backend/frontend proxy: failure, approval, verification, SSE/report, reset, and rejection; original verified history persisted |
| Live AI with Docker | Not verified because Docker and an installed local model were unavailable |
| Browser visual QA | Separate-tab navigation stopped at the Windows URL-policy check; visual click-through remains unverified |

Existing Python and Ollama installations were reused. Neither runtime was
reinstalled, and no model was downloaded. A model exposed through another coding
assistant does not establish a usable local Ollama model.

The user explicitly authorized the optional trusted local demo runner. It is
disabled by default and can execute only the complete, literal-hash-pinned
bundled scenarios or exact deterministic approved candidates. Tests and logs are
real; hypotheses and repairs in Demo Mode are explicitly predefined. This path
uses the host interpreter and does not provide Docker isolation. Arbitrary
imports and Live AI patches remain Docker-only.

For the prepared workspace, start the backend with the opt-in flag and start the
frontend in a second terminal:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1 -EnableTrustedDemoRunner
```

```powershell
npm.cmd --prefix frontend run dev
```

For a clean clone, run `scripts/setup.ps1` first without `-BuildRunner`. It reuses
an existing `.venv`, otherwise locates Python on `PATH` or under
`%LOCALAPPDATA%\Programs\Python`; `-PythonPath` selects an existing interpreter.
It installs dependencies but does not install a Python runtime. Docker is needed
only when building/using the Docker execution path.

Live AI requires an installed non-cloud model visible in Ollama's own inventory,
a reachable Linux-container Docker daemon, and a built `rootcause-runner:local`
image. Set `RC_OLLAMA_MODEL` to the exact installed name, or leave it empty for
local Gemma detection. The application never silently replaces failed live
inference with Demo Mode.

See [README setup commands](../README.md), [the repeatable demo](demo.md), and
[executed checks and limitations](verification.md).
