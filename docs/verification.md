# Verification record

Recorded on **28 October 2026**. Demo conclusions are explicitly preconfigured; the test outcomes below were actually executed.

| Check | Observed result |
| --- | --- |
| Complete trusted backend suite | **132 passed, 1 skipped**, 2 upstream deprecation warnings |
| TypeScript and Vite production build | Passed after the Demo/Live workflow and professional console updates |
| Python and npm dependency audits | Previous audit reported zero known vulnerabilities; this update adds no dependencies |
| Running FastAPI service | Started successfully on loopback port 8000 with trusted-demo opt-in |
| Running frontend | HTTP 200 on port 5173; API proxy returned all three scenarios |
| Real HTTP investigation workflows | All three scenarios reproduced failures, proposed actual diffs, applied approved fixes, and passed real pytest verification |
| SSE and reports | Actual events, terminal completion, and labeled Markdown reports returned successfully |
| Reset | Every scenario reproduced its original failure again in a fresh investigation; verified history remained available |
| Imported projects | Refused Demo Mode/local execution; Live AI and imports remain Docker-only |
| Trusted local runner boundary | Changed source/tests, extra files, disabled execution, and unknown scenarios rejected before execution |
| Windows timeout cleanup | Real parent/child test process tree terminated by the runner job after timeout |
| Legacy SQLite database | Additive migration preserved existing project records |
| PowerShell scripts | Syntax validation passed |
| Visual browser click-through | Not completed: Windows browser automation stopped at its URL-policy confidence check |
| Live Ollama/Docker integration | Still unverified here: no installed local model and Docker unavailable |

Actual black-box results through the running frontend API proxy:

| Scenario | Baseline | Approved candidate | Reset |
| --- | --- | --- | --- |
| API configuration | 4 passed, **1 failed**, exit 1 | **5 passed**, 0 failed/errors, exit 0 | Original failure reproduced |
| SQLite database query | 2 passed, **3 failed**, exit 1 | **5 passed**, 0 failed/errors, exit 0 | Original failures reproduced |
| Hidden logical bug | 4 passed, **1 failed**, exit 1 | **5 passed**, 0 failed/errors, exit 0 | Original failure reproduced |

Each verified outcome used the same test identities and runner before and after, repaired at least one failing test, and reported no missing or regressed tests. All three ran with `trusted_local_demo`, not Docker. They executed exact, manifest-pinned bundled baseline/candidate bytes in fresh temporary directories. No imported project or arbitrary model-generated patch was executed on the host.

The live integration test remains opt-in (`RC_RUN_LIVE=1`) and was skipped. Demo API integration tests ran real pytest subprocesses while asserting that no live AI provider was called. Other unit tests use scoped test doubles where appropriate; production code does not use those doubles.

The frontend was redesigned with explicit modes, three scenario cards, a stage navigator, findings panel, readable evidence/diffs, approval controls, verification details, reports and reset. The production build passed, but no visual or click-through claim is made because browser automation stopped before opening the local dashboard.

Start the model-free demo in two terminals:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1 -EnableTrustedDemoRunner
```

```powershell
npm.cmd --prefix frontend run dev
```

Open <http://127.0.0.1:5173>. See [the 90-second demonstration](demo.md) and [README](../README.md) for clean-clone setup, Live AI requirements and security boundaries.
