# Local API reference

Base URL: `http://127.0.0.1:8000`. OpenAPI documentation is at `/docs`, with the
schema at `/openapi.json`. Vite proxies `/api` to this backend. JSON requests
reject unknown fields. Keep this single-user service on loopback; it has no
account or API-key authorization layer.

## Modes and execution

| Investigation mode | Analysis | Execution |
| --- | --- | --- |
| `demo` | Explicitly labeled predefined hypotheses/repairs; no model call | Docker when available, otherwise the explicitly enabled trusted local runner for complete pinned scenarios only |
| `live` | Configured local Ollama model | Docker only, including imported projects and model-generated candidates |

`mode` defaults to `live`. Demo Mode accepts only projects created through the
bundled-scenario endpoint. It verifies the entire baseline/candidate against
literal shipped file hashes. The trusted local exception is disabled by default
and requires `RC_ENABLE_TRUSTED_DEMO_RUNNER=true`, or the equivalent backend
startup flag. It executes trusted definition bytes with the host interpreter;
it does not provide Docker isolation. Provider failure never changes modes.

## Endpoints

| Method and path | Request | Response |
| --- | --- | --- |
| `GET /api/health` | None | Live `status`, `ai`, `sandbox`, and separate `demo` readiness |
| `GET /api/demo/scenarios` | None | Three scenario records with `id`, `title`, `category`, `description`, `expected_failure` |
| `POST /api/demo` | JSON `{"scenario_id":"api-config"}`; omitted body selects `api-config` | `201` new managed project from the original bundled baseline |
| `GET /api/projects` | None | Project records, newest first |
| `POST /api/projects/directory` | JSON `{"path":"C:/approved-root/my-project"}` | `201` validated imported project |
| `POST /api/projects/archive` | Multipart form field `file` with a ZIP | `201` validated imported project |
| `GET /api/investigations` | None | Up to 200 investigation summaries, newest first |
| `POST /api/investigations` | JSON `{"project_id":"<id>","mode":"demo","logs":""}` | `202` queued asynchronous investigation |
| `GET /api/investigations/{id}` | None | Complete persistent investigation and events |
| `POST /api/investigations/{id}/approve` | None | `202` recorded approval; isolated candidate application and tests start asynchronously |
| `POST /api/investigations/{id}/reject` | None | Recorded rejection; source remains unchanged |
| `POST /api/investigations/{id}/reset` | None | `202` new Demo Mode investigation using a newly imported original scenario; previous history remains |
| `GET /api/investigations/{id}/events` | Optional integer `after` and/or `Last-Event-ID` | Persistent, resumable SSE stream |
| `GET /api/investigations/{id}/report` | None | Downloadable `text/markdown` report |

Scenario IDs are `api-config`, `database-query`, and `logical-total`. Reset is
available only for a bundled Demo Mode investigation at a stopped state,
including `awaiting_approval`. It returns a **new investigation ID** and leaves
the previous investigation, approval decision, candidate, and events intact.

Project metadata includes `id`, `name`, `file_count`, `created_at`, and nullable
`scenario_id`. Investigations additionally expose `mode`, `scenario_id`,
`analysis_label`, and `runner_type`, alongside status, summary, error, timestamps,
evidence, hypotheses, diagnostics, patch, baseline, verification, and events.
The demo analysis label discloses **Preconfigured AI Analysis**. A missing patch
or test result is `null`, never an implied success.

IDs are server-issued 32-character lowercase hexadecimal strings. Directory
imports stay inside `RC_IMPORT_ROOTS`. ZIPs are capped at 32 MiB, with expanded
file/count/path validation and a streamed request-body limit. Submitted logs
have a 100,000-character limit.

## Health and result semantics

`status: ready` still means that **Live AI** has a usable local model and Docker
runner image. A model-free demo may be executable while this status remains
`degraded`. Check `demo.execution_available`; `demo.available` describes the
presence of bundled scenarios, while `demo.local_runner_enabled` and
`demo.local_runner` describe the opt-in host execution path.

The proposal sequence is:

```text
queued -> collecting -> baseline -> analyzing -> diagnosing -> proposing -> awaiting_approval
```

Approval continues through `applying -> verifying`. The patch status moves from
`proposed` to `approved` to `applied`, or to `rejected`. Applying a patch is not a
verification result. Only the displayed `proposed` patch on an
`awaiting_approval` investigation may be approved/rejected.

| Investigation state | Meaning |
| --- | --- |
| `verified` | An observed failing baseline became a fully passing suite with matching unique tests and runner, at least one fixed failure, and no lost/regressed tests |
| `failed` | Investigation/application failed, or candidate verification criteria were unmet |
| `regression` | A previously passing test failed or disappeared |
| `blocked` | Model, validation, or execution infrastructure prevented completion |
| `insufficient_evidence` | Evidence was absent or the baseline already passed |
| `interrupted` | Restart/cancellation stopped active work; automatic resumption is disabled |
| `awaiting_approval` | Reviewable proposal; edits have not been applied |
| `rejected` | Developer rejected the proposal |

Each investigation preserves the imported baseline and applies approved edits
only to a separate candidate. A new investigation starts from original imported
source. Additive SQLite migration preserves earlier records and marks their
existing behavior as Live AI; no history reset is required.

Test-run statuses are `passed`, `failed`, `unavailable`, `timeout`, and `error`.
Results include `exit_code`, `stdout`, `stderr`, `duration_seconds`, `passed`,
`failed`, `errors`, `skipped`, `tests`, `command`, and `runner`. The runner is
`docker` or `trusted_local_demo`; a local result includes `isolation_note` and
the validated `variant` (`baseline` or `candidate`). Investigation `runner_type`
may be `unavailable` when no executor could run. Verification adds
`regressions`, `missing_tests`, `fixed_tests`, `coverage_equal`, `same_runner`,
and `verified`. A runner switch, empty suite, skipped test, unavailable baseline,
or missing test prevents verified status.

## Manual model-free demonstration

Start the backend with `-EnableTrustedDemoRunner`, then create a scenario and
explicitly request Demo Mode:

```powershell
$baseUrl = 'http://127.0.0.1:8000'
Invoke-RestMethod "$baseUrl/api/health"
Invoke-RestMethod "$baseUrl/api/demo/scenarios"
$demoBody = @{ scenario_id = 'api-config' } | ConvertTo-Json
$project = Invoke-RestMethod "$baseUrl/api/demo" -Method Post -ContentType 'application/json' -Body $demoBody
$startBody = @{ project_id = $project.id; mode = 'demo'; logs = '' } | ConvertTo-Json
$run = Invoke-RestMethod "$baseUrl/api/investigations" -Method Post -ContentType 'application/json' -Body $startBody
$investigationId = $run.id
Invoke-RestMethod "$baseUrl/api/investigations/$investigationId"
```

Poll the GET endpoint or observe SSE until `awaiting_approval`. Inspect the diff
and actual baseline before choosing one decision:

```powershell
# After reviewing the displayed patch:
Invoke-RestMethod "$baseUrl/api/investigations/$investigationId/approve" -Method Post
```

```powershell
# Alternatively, reject without applying it:
Invoke-RestMethod "$baseUrl/api/investigations/$investigationId/reject" -Method Post
```

After verification reaches a stopped state, reset without deleting the old run:

```powershell
$freshRun = Invoke-RestMethod "$baseUrl/api/investigations/$investigationId/reset" -Method Post
$freshRun.id
Invoke-WebRequest "$baseUrl/api/investigations/$investigationId/report" -OutFile '.\investigation-report.md'
```

For Live AI, use `mode = 'live'` and an imported project ID. An installed local
model and Docker are required; local demo opt-in cannot execute Live AI code.

## Events and errors

SSE events contain the persistent numeric `id` followed by JSON `data` with
`id`, `investigation_id`, `type`, `message`, `data`, and `created_at`. Events after
the greater of `after` and `Last-Event-ID` replay before new events. Heartbeats
are comments; `event: done` closes a stopped stream, including at approval.
Reconnect after approval to watch verification. Events record actual workflow
transitions and observations, not simulated percentages or model-token output.

```powershell
curl.exe -N "http://127.0.0.1:8000/api/investigations/<id>/events?after=0"
```

Errors use JSON `detail`: `400` invalid intake/mode/cursor, `403` untrusted
browser mutation origin, `404` unknown record, `409` invalid/repeated decision or
reset, `413` oversized body/archive, `422` invalid request schema, and `429` a
full task queue. Later asynchronous errors persist in the investigation and
events. A `202` response acknowledges queued work; it does not claim success.
