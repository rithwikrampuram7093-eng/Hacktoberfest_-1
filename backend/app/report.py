from __future__ import annotations


def render_report(investigation: dict) -> str:
    item = investigation
    lines = ["# RootCause AI investigation report", "", f"Project: {item['project_name']}", f"Investigation: {item['id']}",
             f"Created: {item['created_at']}", f"Status: **{item['status']}**", "", item["summary"], "",
             "Verification is limited to the supplied test suite. A model hypothesis is not an observed fact.", "", "## Observed evidence", ""]
    for evidence in item["evidence"]:
        lines += [f"### {evidence['id']} · {evidence['kind']}", f"Location: {evidence['path']}:{evidence['line']} · Observed: {evidence['observed_at']}", "", "````text", evidence["content"], "````", ""]
    lines += ["## Ranked hypotheses (AI generated)", ""]
    for hypothesis in item["hypotheses"]:
        lines += [f"### {hypothesis['title']}", hypothesis["reasoning"], f"Model confidence: {hypothesis['confidence']:.0%}; evidence ranking score: {hypothesis.get('score', 0)}", "Supporting evidence: " + ", ".join(hypothesis["supporting_evidence"]), "Contradicting evidence: " + (", ".join(hypothesis["contradicting_evidence"]) or "None cited; absence of contradiction is not proof"), ""]
    lines += ["## Passive diagnostic observations", ""]
    for diagnostic in item["diagnostics"]:
        lines += [f"- {diagnostic['tool']} · {diagnostic['path']} · {diagnostic['status']}: {diagnostic['observation']}"]
    lines += ["", "## Proposed patch", ""]
    if item.get("patch"):
        patch = item["patch"]
        lines += [f"Decision: {patch['status']}", patch.get("explanation", ""), "", "````diff", patch["diff"], "````", ""]
    else:
        lines += ["No valid patch was produced.", ""]
    for label, result in (("Baseline tests", item.get("baseline")), ("Post-patch tests", item.get("verification"))):
        lines += [f"## {label}", ""]
        if not result:
            lines += ["Not executed.", ""]
            continue
        lines += [f"Status: {result['status']} · exit code: {result['exit_code']} · duration: {result['duration_seconds']}s", f"Passed: {result['passed']} · Failed: {result['failed']} · Errors: {result['errors']} · Skipped: {result['skipped']}",
                  "", "Command: " + " ".join(result.get("command", [])), "", "````text", result["stdout"], result["stderr"], "````", ""]
        if result.get("regressions"):
            lines += ["Regressions: " + ", ".join(result["regressions"]), ""]
    lines += ["## Activity audit trail", ""]
    for event in item.get("events", []):
        lines += [f"- {event['created_at']} · {event['type']} · {event['message']}"]
    if item.get("error"):
        lines += ["", "## Limitation", "", item["error"]]
    return "\n".join(lines) + "\n"
