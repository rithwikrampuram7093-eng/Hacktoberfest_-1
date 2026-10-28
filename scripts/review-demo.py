"""Drive the real local API demo with an explicit human patch decision."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api"
TERMINAL = {"awaiting_approval", "verified", "failed", "blocked", "regression", "interrupted", "rejected", "insufficient_evidence"}


def call(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def wait(identity: str) -> dict:
    last_status = None
    deadline = time.monotonic() + 2000
    while time.monotonic() < deadline:
        item = call(f"/investigations/{identity}")
        if item["status"] != last_status:
            print(f"[{item['status']}] {item['summary']}")
            last_status = item["status"]
        if item["status"] in TERMINAL:
            return item
        time.sleep(0.5)
    raise TimeoutError("Investigation did not finish before the client timeout; inspect its persisted state")


def main() -> int:
    health = call("/health")
    if health["status"] != "ready":
        print(json.dumps(health, indent=2))
        print("Configure Docker and a local Ollama model before running the full demo.")
        return 2
    project = call("/demo", {})
    item = call("/investigations", {"project_id": project["id"], "logs": ""})
    identity = item["id"]
    print(f"Investigation: {identity}")
    item = wait(identity)
    if item["status"] != "awaiting_approval":
        return 1
    print("\n" + item["patch"]["explanation"] + "\n\n" + item["patch"]["diff"])
    decision = input("Type APPROVE to apply this displayed patch in isolation and run verification; any other response rejects it: ")
    call(f"/investigations/{identity}/{'approve' if decision == 'APPROVE' else 'reject'}", {})
    item = wait(identity)
    for label in ("baseline", "verification"):
        result = item.get(label)
        if result:
            print(f"\n{label}: {result['status']} / exit {result['exit_code']}")
            print(result["stdout"] + "\n" + result["stderr"])
    print(f"Report: {BASE}/investigations/{identity}/report")
    return 0 if item["status"] == "verified" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, TimeoutError, KeyboardInterrupt) as exc:
        print(f"Demo client stopped: {exc}")
        raise SystemExit(2)
