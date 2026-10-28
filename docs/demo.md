# 90-second hackathon demonstration

Prepare dependencies once with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1`. Docker, Ollama, internet access and API keys are not required during the bundled demo after setup.

Start these commands in two terminals opened at the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1 -EnableTrustedDemoRunner
```

```powershell
npm.cmd --prefix frontend run dev
```

Open <http://127.0.0.1:5173>. The explicit flag enables trusted local execution for the three exact bundled scenarios only. It does not enable host execution for imported projects or Live AI patches.

| Time | Action and narration |
| --- | --- |
| 0–10 seconds | Select **Demo Mode**. State: “This is preconfigured analysis for reproducible examples; the diagnostics, failures and verification tests are real.” Point to **Demo Investigation — Preconfigured AI Analysis**. |
| 10–20 seconds | Choose **Inventory API configuration** and select **Start demo**. The backend copies the failing fixture and executes pytest. |
| 20–35 seconds | Open **Evidence** and the baseline test output. Show the actual KeyError, source/configuration locations and the baseline with 4 passing tests and 1 failure. These counts are expected for the unchanged fixture; use the recorded current result on screen. |
| 35–50 seconds | Open **Hypotheses**. Explain the primary configured diagnosis and cited evidence. Show the alternative explanation and real passive diagnostic observations. Do not describe the configured diagnosis as autonomous discovery. |
| 50–65 seconds | Open **Proposed patch**. Review the exact configuration-lookup repair. Select **Approve patch & run tests** to record approval and apply the patch to a separate candidate workspace. |
| 65–80 seconds | Open **Test results**. Show the actual baseline versus candidate: five passing tests, exit zero, matching coverage and no observed regressions. Claim a verified repair only if the investigation status is **Verified**. |
| 80–90 seconds | Download the report. Select **Reset Demo** to reproduce the original failure in a fresh run; show the verified previous investigation retained in **History**. |

These timings are presentation targets, not timers built into the application. Wait for actual backend completion; never substitute a presentation claim for a recorded result.

The other scenarios use the same flow:

| Scenario | Failure to show | Actual development result |
| --- | --- | --- |
| SQLite inventory query | `sqlite3.OperationalError` from a nonexistent projection column | 2 passing / 3 failing baseline tests → 5 passing candidate tests |
| Order total calculation | Failing expected-versus-actual assertion, without an application exception | 4 passing / 1 failing baseline test → 5 passing candidate tests |

A terminal demonstration is also available. It prints the real diff and waits for the exact word `APPROVE` before applying it:

```powershell
.\.venv\Scripts\python.exe scripts\review-demo.py --mode demo --scenario api-config
.\.venv\Scripts\python.exe scripts\review-demo.py --mode demo --scenario database-query
.\.venv\Scripts\python.exe scripts\review-demo.py --mode demo --scenario logical-total
```

Demo Mode uses deterministic explanations and repairs tied to literal source/test hashes. The local runner executes only complete approved fixture variants using trusted definition bytes, a fresh temporary workspace, a minimal environment and process/time limits. It is trusted host execution, not Docker isolation. See [architecture](architecture.md) for the boundary.

Live AI Mode remains separate and needs an actual installed Ollama model plus Docker. A live model failure stays visible and may offer a button to start a new Demo investigation; it never silently replaces the live result. The local runner cannot execute arbitrary imported projects or model-generated candidates.

If local execution is disabled and Docker is unavailable, Demo Mode can still collect source evidence and show a clearly labeled proposal. It must show unavailable tests and cannot claim a verified repair. Enable the flag above and start a fresh demo to establish real before-and-after results. If a test fails, times out or regresses, present the actual output.

For clean-clone setup, exact Live AI requirements and the current verification record, see [README](../README.md) and [verification](verification.md).