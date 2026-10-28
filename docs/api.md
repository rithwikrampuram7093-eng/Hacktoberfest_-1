# Local API reference

Base URL: `http://127.0.0.1:8000`. Interactive OpenAPI documentation is available
at `/docs`, with the schema at `/openapi.json`. The Vite development server
proxies `/api` to this backend. JSON schemas reject unknown request fields.

The service is for one local developer. It has no login or API-key scheme. Bind
to loopback and do not expose it publicly. Browser mutations are limited to
known local origins and cross-site mutations are rejected; these controls do not
replace an authorization system. Project contents and report text remain
untrusted data.

## Endpoints

| Method and path | Request | Response |
| --- | --- | --- |
| `GET /api/health` | None | `status` (`ready` or `degraded`), `ai`, `sandbox` readiness details |
| `GET /api/projects` | None | Imported project records, newest first |
| `POST /api/projects/directory` | JSON `{"path":"C:/approved-root/my-project"}` | `201` project metadata after validated copy |
| `POST /api/projects/archive` | Multipart form field `file` containing a ZIP | `201` project metadata after validated extraction |
| `POST /api/demo` | None | `201` new project copied from the failing Order Service sample |
| `GET /api/investigations` | None | Up to 200 investigation summaries, newest first |
| `POST /api/investigations` | JSON `{"project_id":"<32 lowercase hex characters>","logs":"optional error text"}` | `202` queued investigation; work starts asynchronously |
| `GET /api/investigations/{id}` | None | Complete persistent investigation, including events |
| `POST /api/investigations/{id}/approve` | None | `202` decision recorded; candidate application and verification start asynchronously |
| `POST /api/investigations/{id}/reject` | None | Rejected investigation; no application source is changed |
| `GET /api/investigations/{id}/events` | Optional `after` integer query and/or `Last-Event-ID` header | SSE activity stream, resumable from an event ID |
| `GET /api/investigations/{id}/report` | None | Downloadable `text/markdown` report for the current state |

Project metadata contains `id`, `name`, `file_count`, and `created_at`. An
investigation contains `id`, `project_id`, `project_name`, `status`, `summary`,
`error`, timestamps, `evidence`, `hypotheses`, `diagnostics`, `patch`, `baseline`,
`verification`, and `events`. A missing result or patch is `null`; it does not
represent a successful execution.

Directory intake must stay under `RC_IMPORT_ROOTS`. Archive upload is capped at
32 MiB, with additional expanded-content, path, and file-count checks. Submitted
logs are limited to 100,000 characters. IDs are server-issued 32-character
lowercase hexadecimal values.

## State and result semantics

The normal proposal sequence is:

```text
queued → collecting → baseline → analyzing → diagnosing → proposing → awaiting_approval
```

Approval continues through `applying → verifying`; rejection yields `rejected`.
Other stopped states are:

| State | Meaning |
| --- | --- |
| `verified` | An actual failing baseline became an entirely passing matching test suite with no lost or regressed tests |
| `failed` | Investigation/application failed, or the candidate did not satisfy verification criteria |
| `regression` | A previously passing test failed or disappeared |
| `blocked` | Provider, validation, or verification infrastructure prevented completion |
| `insufficient_evidence` | No supported evidence, or the baseline already passed so no failure was reproduced |
| `interrupted` | Process interruption/restart stopped active work; automatic resumption is disabled |
| `awaiting_approval` | Reviewable proposal; no source changes have been applied |
| `rejected` | Developer rejected the proposal |

Only an investigation currently `awaiting_approval` with a `proposed` patch may
be approved or rejected. The patch object's status progresses from `proposed`
to `approved` to `applied`, or to `rejected`. An `applied` patch is not necessarily
verified. Approval creates an isolated candidate, preserving both imported source
and the investigation baseline. A new investigation uses the unchanged imported
project, not an earlier candidate.

Test-run statuses are independent: `passed`, `failed`, `unavailable`, `timeout`,
and `error`. A test result includes `exit_code`, `stdout`, `stderr`,
`duration_seconds`, `passed`, `failed`, `errors`, `skipped`, `tests`, and the actual
runner `command`. Infrastructure failures can have no exit code. Verification
also records `regressions`, `missing_tests`, `fixed_tests`, `coverage_equal`, and
`verified`. Empty or skipped suites cannot verify a repair.

Health returns `ready` only when a local usable model and the built Docker image
are both available. `degraded` allows the UI and intake to operate but does not
establish that analysis or test verification can run. An unavailable baseline
is preserved as such; static analysis may still be attempted, and it cannot be
promoted to a verified repair without observed failing and passing test runs.

## Events and reconnects

Each activity event is sent as a standard SSE record:

```text
id: <persistent numeric event ID>
data: <JSON activity record>

```

The JSON record contains `id`, `investigation_id`, `type`, `message`, `data`, and
`created_at`. Heartbeats are SSE comments. The endpoint replays events after the
greater of `after` and `Last-Event-ID`, then streams new events. It emits
`event: done` and closes at a stopped state, including `awaiting_approval`.
Reconnect after approval to watch verification. Events report actual stage
transitions and observations; they are not AI-token or percentage simulation.

```powershell
curl.exe -N "http://127.0.0.1:8000/api/investigations/<id>/events?after=0"
```

## Manual HTTP demonstration

These commands operate on a new managed copy. Docker and an installed local
model are required for the full flow:

```powershell
$baseUrl = 'http://127.0.0.1:8000'
Invoke-RestMethod "$baseUrl/api/health"
$project = Invoke-RestMethod "$baseUrl/api/demo" -Method Post
$requestBody = @{ project_id = $project.id; logs = '' } | ConvertTo-Json
$investigation = Invoke-RestMethod "$baseUrl/api/investigations" -Method Post -ContentType 'application/json' -Body $requestBody
$investigationId = $investigation.id
Invoke-RestMethod "$baseUrl/api/investigations/$investigationId"
```

Inspect the current investigation and patch diff in the dashboard or the GET
response. After an explicit review, choose **one** decision:

```powershell
# Approve the displayed proposal, then inspect actual verification output.
Invoke-RestMethod "$baseUrl/api/investigations/$investigationId/approve" -Method Post
```

```powershell
# Or reject it without applying the proposed edits.
Invoke-RestMethod "$baseUrl/api/investigations/$investigationId/reject" -Method Post
```

Download the report at any state:

```powershell
Invoke-WebRequest "$baseUrl/api/investigations/$investigationId/report" -OutFile '.\investigation-report.md'
```

## Errors

Validation errors use normal FastAPI JSON `detail` responses. Common statuses:
`400` invalid intake or event cursor, `403` untrusted browser mutation origin,
`404` unknown project/investigation, `409` invalid or repeated review decision,
`413` oversized request/archive, `422` request schema validation, and `429` a full
active-task queue. Errors after an asynchronous start are recorded in the
investigation state, error field, and audit trail; the initial `202` response is
not a success claim.
