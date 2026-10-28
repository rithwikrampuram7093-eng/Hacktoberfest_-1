# Order Service

A deliberately failing standard-library Python application for RootCause AI's
live investigation. It exposes a small HTTP API and stores inventory in an
in-memory SQLite database. No external service, secret, or internet connection is
needed to reproduce the failures.

The behavior contract lives in `tests/test_service.py`. The supplied configuration
is `settings.json`. The test suite exercises API configuration, inventory data,
order calculation, encoding, rounding, and input validation. Multiple failing
tests can share one underlying defect. Repair application source and preserve the
test suite.

Use **Load demo** in RootCause AI, then start an investigation. RootCause copies
this directory into its managed project store and runs the actual tests in its
restricted Docker runner. Baseline output supplies the error logs and tracebacks;
this project intentionally contains no pre-recorded failure log or repair patch.

To run the tests manually from the repository root, first build the runner image
as described in the root README, then use the runner's container restrictions:

```powershell
$project = (Resolve-Path .\samples\order-service).Path
$rawReport = docker run --rm --pull never --network none --ipc none --read-only --init --cap-drop ALL --security-opt no-new-privileges --pids-limit 96 --memory 256m --memory-swap 256m --cpus 1 --user 10001:10001 --ulimit nofile=128:128 --ulimit core=0 --tmpfs "/work:rw,nosuid,nodev,noexec,size=134217728,mode=1770,uid=10001,gid=10001" --tmpfs "/tmp:rw,nosuid,nodev,noexec,size=16777216,mode=1777" --mount "type=bind,source=$project,target=/project,readonly" rootcause-runner:local
$dockerExitCode = $LASTEXITCODE
$testReport = $rawReport | ConvertFrom-Json
$testReport.stdout
$testReport | Select-Object passed, failed, errors, skipped, exit_code
Write-Output "Docker exit code: $dockerExitCode"
```

The container should exit nonzero before a repair. Its trusted runner returns a
JSON report; the commands above display its actual pytest output and counts.
Read the real test output to
determine the failures. Do not execute imported applications or their tests on
the host. The dashboard also enforces a host-side timeout and cleans up timed-out
containers; use it for the complete controlled workflow.

For an isolated HTTP demonstration, the app entry point is
`python service.py --host 0.0.0.0 --port 8080`. The available routes are
`GET /health`, `GET /api/inventory-url?sku=SKU-42`,
`GET /api/stock?sku=SKU-42`, and `POST /api/quote` with JSON
`{"items":[{"unit_price":"19.95","quantity":2}]}`. API startup is optional;
the RootCause investigation uses pytest and needs no listening service.
