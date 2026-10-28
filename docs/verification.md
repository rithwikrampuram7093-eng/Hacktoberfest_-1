# Executed verification

Recorded on **28 October 2026**. These are observed development checks; they are
not a claim that the real Docker/Gemma repair demonstration has passed.

| Check | Observed result |
| --- | --- |
| `.venv\\Scripts\\python.exe -m pytest -q` | **95 passed, 1 skipped**, 2 third-party deprecation warnings |
| `npm.cmd --prefix frontend run build` | TypeScript checks and Vite production build passed |
| Python dependency audit (`python -m pip_audit`) | No known vulnerabilities found after updating vulnerable initial pins, including transitive Starlette |
| Frontend dependency audit (`npm.cmd audit`) | No known vulnerabilities reported |
| FastAPI startup using patched dependencies | Successful on loopback port 8000 |
| Frontend development HTTP | HTTP 200 on loopback port 5173 |
| Built frontend preview HTTP | HTTP 200 on loopback port 4173 |
| Preview API proxy and POST origin | Health request and sample import succeeded through port 4173 |
| Persistent history | Actual blocked investigation remained after backend restart |
| Live project intake | Bundled Order Service copied successfully, 5 supported files |
| Live investigation with this machine's runtimes | Collected 6 evidence records; baseline unavailable; blocked with explicit missing Gemma model; zero hypotheses and no patch |
| SSE and Markdown report | Both returned HTTP 200; terminal event and blocked outcome present |
| Windows scripts | All PowerShell setup/start scripts passed syntax parsing |
| Visual browser QA | Not completed: computer-use tooling stopped because it could not determine Chrome's current URL confidently enough to enforce policy |
| Real model-generated, Docker-verified repair | **Not executed**: Docker unavailable and Ollama inventory empty |

The skipped test is the explicit live-runtime integration test in
`backend/tests/test_live.py`. Enable it only after the local model, Docker daemon
and trusted runner image are ready:

```powershell
$env:RC_RUN_LIVE='1'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_live.py -q
Remove-Item Env:RC_RUN_LIVE
```

The 95 passing trusted tests exercise intake boundaries, secret redaction,
allowlisted diagnostics, structured-provider validation, stale patch and rollback
handling, custom pytest-file protection, Docker command restrictions, result
validation, timeouts, approval/rejection, persistence, SSE, reports and
regression/coverage rules. Unit tests use clearly scoped test doubles for model
and sandbox responses; production code never uses those doubles.

No imported-project or sample code was executed on the host. The deliberately
failing sample tests remain unexecuted until Docker is available. No fabricated
sample traces, AI conclusions or test outcomes were added to the application.

For the full human-approved flow, start the backend and run:

```powershell
.\.venv\Scripts\python.exe scripts\review-demo.py
```

This client requires healthy actual runtimes, prints the returned patch, waits
for `APPROVE`, and then displays real baseline and post-patch results. A failure
or missing requirement produces a nonzero exit status.
