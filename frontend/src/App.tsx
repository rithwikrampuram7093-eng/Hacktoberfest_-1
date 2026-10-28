import { useCallback, useEffect, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Asterisk,
  Beaker,
  BookOpen,
  Box,
  Braces,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleDot,
  Clock3,
  Command,
  Copy,
  FileCode2,
  FileSearch,
  FileText,
  FlaskConical,
  Folder,
  FolderGit2,
  GitBranch,
  GitCompareArrows,
  History,
  Info,
  Layers3,
  ListFilter,
  LoaderCircle,
  Menu,
  Network,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  Terminal,
  TriangleAlert,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "./components/ui/button";
import { Dialog } from "./components/ui/dialog";
import {
  api,
  type Evidence,
  type Hypothesis,
  type Investigation,
  type InvestigationEvent,
  type InvestigationSummary,
  type Project,
  type RuntimeHealth,
  type TestResult,
} from "./lib/api";
import { cn, formatStatus, relativeTime } from "./lib/utils";

type View = "workspace" | "projects" | "history" | "runtime";
type Notice = { message: string; type: "success" | "error" | "info" };
const terminalStatuses = [
  "completed",
  "verified",
  "failed",
  "rejected",
  "blocked",
  "error",
  "no_patch",
  "cancelled",
  "regression",
  "insufficient_evidence",
  "interrupted",
];
const isRunning = (status?: string) =>
  !!status &&
  !terminalStatuses.includes(status) &&
  status !== "awaiting_approval";
const statusTone = (status: string) =>
  ["completed", "verified", "passed"].includes(status)
    ? "green"
    : ["failed", "error", "rejected", "regression"].includes(status)
      ? "red"
      : ["awaiting_approval", "blocked", "unavailable", "timeout"].includes(
            status,
          )
        ? "amber"
        : "purple";
const safeConfidence = (value: number) =>
  Math.round(
    Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0)) * 100,
  );

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("status-badge", `tone-${statusTone(status)}`)}>
      <span className="status-dot" />
      {formatStatus(status)}
    </span>
  );
}
function EmptyState({
  icon: Icon,
  title,
  description,
  children,
  compact = false,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  children?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cn("empty-state", compact && "empty-compact")}>
      <div className="empty-icon">
        <Icon size={25} strokeWidth={1.5} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {children && <div className="empty-actions">{children}</div>}
    </div>
  );
}
function Loading({ label = "Loading investigation" }: { label?: string }) {
  return (
    <div className="loading-state">
      <LoaderCircle className="spin" size={22} />
      <span>{label}…</span>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<View>("workspace");
  const [projects, setProjects] = useState<Project[]>([]);
  const [history, setHistory] = useState<InvestigationSummary[]>([]);
  const [health, setHealth] = useState<RuntimeHealth | null>(null);
  const [healthError, setHealthError] = useState("");
  const [activeId, setActiveId] = useState<string | null>(() => {
    try {
      return localStorage.getItem("rootcause-investigation");
    } catch {
      return null;
    }
  });
  const [investigation, setInvestigation] = useState<Investigation | null>(
    null,
  );
  const [liveEvents, setLiveEvents] = useState<InvestigationEvent[]>([]);
  const [streamState, setStreamState] = useState<
    "idle" | "connecting" | "connected" | "reconnecting"
  >("idle");
  const [loading, setLoading] = useState(true);
  const [activeLoading, setActiveLoading] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [intakeMode, setIntakeMode] = useState("directory");
  const [projectId, setProjectId] = useState("");
  const [directory, setDirectory] = useState("");
  const [archive, setArchive] = useState<File | null>(null);
  const [logs, setLogs] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [formError, setFormError] = useState("");
  const [selectedTab, setSelectedTab] = useState("evidence");
  const [mobileNav, setMobileNav] = useState(false);
  const [historyQuery, setHistoryQuery] = useState("");
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRequest = useRef(0);

  const notify = useCallback(
    (message: string, type: Notice["type"] = "info") => {
      setNotice({ message, type });
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
      noticeTimer.current = setTimeout(() => setNotice(null), 7000);
    },
    [],
  );

  const refreshCollections = useCallback(async () => {
    const result = await Promise.allSettled([
      api<Project[]>("/projects"),
      api<InvestigationSummary[]>("/investigations"),
    ]);
    if (result[0].status === "fulfilled") setProjects(result[0].value);
    if (result[1].status === "fulfilled") setHistory(result[1].value);
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const result = await api<RuntimeHealth>("/health");
      setHealth(result);
      setHealthError("");
    } catch (error) {
      setHealth(null);
      setHealthError((error as Error).message);
    }
  }, []);

  const refreshInvestigation = useCallback(
    async (id: string, showLoading = false) => {
      const request = ++activeRequest.current;
      if (showLoading) setActiveLoading(true);
      try {
        const result = await api<Investigation>(
          `/investigations/${encodeURIComponent(id)}`,
        );
        if (request === activeRequest.current) setInvestigation(result);
      } catch (error) {
        if (request === activeRequest.current && showLoading) {
          notify((error as Error).message, "error");
          setInvestigation(null);
        }
      } finally {
        if (request === activeRequest.current) setActiveLoading(false);
      }
    },
    [notify],
  );

  useEffect(() => {
    void Promise.all([refreshHealth(), refreshCollections()]).finally(() =>
      setLoading(false),
    );
    const timer = setInterval(() => {
      void refreshHealth();
      void refreshCollections();
    }, 20000);
    return () => clearInterval(timer);
  }, [refreshHealth, refreshCollections]);

  useEffect(() => {
    if (!activeId) {
      setInvestigation(null);
      return;
    }
    setLiveEvents([]);
    setInvestigation(null);
    void refreshInvestigation(activeId, true);
    try {
      localStorage.setItem("rootcause-investigation", activeId);
    } catch {
      /* Local persistence is optional. */
    }
  }, [activeId, refreshInvestigation]);

  useEffect(() => {
    if (
      !activeId ||
      !investigation ||
      investigation.status === "awaiting_approval" ||
      terminalStatuses.includes(investigation.status)
    ) {
      setStreamState("idle");
      return;
    }
    setStreamState("connecting");
    const source = new EventSource(
      `/api/investigations/${encodeURIComponent(activeId)}/events`,
    );
    let finished = false;
    const fallback = setInterval(() => {
      void refreshInvestigation(activeId);
    }, 5000);
    source.onopen = () => setStreamState("connected");
    const receive = (message: MessageEvent) => {
      try {
        const event = JSON.parse(message.data) as InvestigationEvent;
        if (!event.message) return;
        setLiveEvents((previous) =>
          previous.some((item) => String(item.id) === String(event.id))
            ? previous
            : [...previous, event],
        );
      } catch {
        return;
      }
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(() => {
        void refreshInvestigation(activeId);
        void refreshCollections();
      }, 200);
    };
    source.onmessage = receive;
    source.addEventListener("activity", receive as EventListener);
    source.addEventListener("done", () => {
      finished = true;
      source.close();
      clearInterval(fallback);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      setStreamState("idle");
      void refreshInvestigation(activeId);
      void refreshCollections();
    });
    source.onerror = () => {
      if (!finished) setStreamState("reconnecting");
    };
    return () => {
      source.close();
      clearInterval(fallback);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [
    activeId,
    investigation?.status,
    refreshInvestigation,
    refreshCollections,
  ]);

  useEffect(() => {
    return () => {
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    };
  }, []);

  const navigate = (next: View) => {
    setView(next);
    setMobileNav(false);
  };
  const selectInvestigation = (id: string) => {
    setActiveId(id);
    setView("workspace");
    setSelectedTab("evidence");
    setMobileNav(false);
  };
  const openIntake = () => {
    setIntakeMode(projects.length ? "existing" : "directory");
    setProjectId(projects[0]?.id || "");
    setFormError("");
    setDialogOpen(true);
  };

  const loadDemo = async () => {
    setBusy("demo");
    try {
      const project = await api<Project>("/demo", { method: "POST" });
      await refreshCollections();
      setProjectId(project.id);
      setIntakeMode("existing");
      setLogs("");
      setFormError("");
      setDialogOpen(true);
      notify(
        "Sample project imported. Start an investigation to collect real evidence.",
        "success",
      );
    } catch (error) {
      notify((error as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  const startInvestigation = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy("start");
    setFormError("");
    try {
      let selectedProjectId = projectId;
      if (intakeMode === "directory") {
        const project = await api<Project>("/projects/directory", {
          method: "POST",
          body: JSON.stringify({ path: directory.trim() }),
        });
        selectedProjectId = project.id;
      }
      if (intakeMode === "archive") {
        if (!archive) throw new Error("Select a ZIP archive first.");
        const body = new FormData();
        body.append("file", archive);
        const project = await api<Project>("/projects/archive", {
          method: "POST",
          body,
        });
        selectedProjectId = project.id;
      }
      if (!selectedProjectId)
        throw new Error("Select a project to investigate.");
      const result = await api<Investigation>("/investigations", {
        method: "POST",
        body: JSON.stringify({ project_id: selectedProjectId, logs }),
      });
      setDialogOpen(false);
      setLogs("");
      setArchive(null);
      selectInvestigation(result.id);
      await refreshCollections();
      notify(
        "Investigation started. Follow the activity feed for observed results.",
        "success",
      );
    } catch (error) {
      setFormError((error as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const reviewPatch = async (decision: "approve" | "reject") => {
    if (!activeId) return;
    setBusy(decision);
    try {
      await api(`/investigations/${encodeURIComponent(activeId)}/${decision}`, {
        method: "POST",
        body: "{}",
      });
      await refreshInvestigation(activeId);
      await refreshCollections();
      notify(
        decision === "approve"
          ? "Patch approved. Follow verification in the activity feed."
          : "Patch rejected. No proposed changes were applied.",
        "success",
      );
      if (decision === "approve") setSelectedTab("tests");
    } catch (error) {
      notify((error as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  const events = [
    ...new Map(
      [...(investigation?.events || []), ...liveEvents].map((event) => [
        String(event.id),
        event,
      ]),
    ).values(),
  ].sort(
    (a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );
  const activeProject = projects.find(
    (project) => project.id === investigation?.project_id,
  );
  const aiAvailable = health?.ai.available;
  const sandboxAvailable = health?.sandbox.available;
  const ready = aiAvailable && sandboxAvailable;
  const tabs = [
    {
      id: "evidence",
      label: "Evidence",
      icon: FileSearch,
      count: investigation?.evidence.length,
    },
    {
      id: "hypotheses",
      label: "Hypotheses",
      icon: Network,
      count: investigation?.hypotheses.length,
    },
    { id: "patch", label: "Proposed patch", icon: GitCompareArrows },
    { id: "tests", label: "Test results", icon: FlaskConical },
    { id: "report", label: "Report", icon: FileText },
  ];

  return (
    <div className="app-shell">
      {mobileNav && (
        <button
          className="mobile-backdrop"
          onClick={() => setMobileNav(false)}
          aria-label="Close navigation"
        />
      )}
      <aside className={cn("sidebar", mobileNav && "sidebar-open")}>
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            navigate("workspace");
          }}
        >
          <span className="brand-mark">
            <Asterisk size={28} strokeWidth={2.2} />
          </span>
          <span>
            rootcause<span className="brand-ai">.ai</span>
          </span>
          <span className="beta-label">BETA</span>
        </a>
        <button
          className="workspace-switch"
          onClick={() => navigate("projects")}
        >
          <span className="workspace-avatar">
            <Command size={18} />
          </span>
          <span>
            <strong>Local workspace</strong>
            <small>Personal workspace</small>
          </span>
          <ChevronDown size={15} />
        </button>
        <div className="nav-section-label">WORKSPACE</div>
        <nav className="nav-links" aria-label="Main navigation">
          <button
            className={cn("nav-item", view === "workspace" && "active")}
            onClick={() => navigate("workspace")}
          >
            <Layers3 size={18} />
            <span>Investigation</span>
            <span className="nav-shortcut">01</span>
          </button>
          <button
            className={cn("nav-item", view === "projects" && "active")}
            onClick={() => navigate("projects")}
          >
            <FolderGit2 size={18} />
            <span>Projects</span>
            <span className="nav-count">{projects.length}</span>
          </button>
          <button
            className={cn("nav-item", view === "history" && "active")}
            onClick={() => navigate("history")}
          >
            <History size={18} />
            <span>History</span>
            {history.length > 0 && (
              <span className="nav-count">{history.length}</span>
            )}
          </button>
          <button
            className={cn("nav-item", view === "runtime" && "active")}
            onClick={() => navigate("runtime")}
          >
            <Server size={18} />
            <span>Runtime & models</span>
            <span
              className={cn(
                "tiny-dot",
                ready ? "green-dot" : health ? "amber-dot" : "",
              )}
            />
          </button>
        </nav>
        <div className="sidebar-recent">
          <div className="nav-section-label">
            RECENT INVESTIGATIONS
            <span>{history.length > 0 ? history.length : "—"}</span>
          </div>
          {history.length ? (
            history.slice(0, 4).map((item) => (
              <button
                key={item.id}
                className={cn(
                  "recent-item",
                  activeId === item.id && view === "workspace" && "selected",
                )}
                onClick={() => selectInvestigation(item.id)}
              >
                <span
                  className={cn("tiny-dot", `dot-${statusTone(item.status)}`)}
                />
                <span>{item.project_name}</span>
                <ChevronRight size={13} />
              </button>
            ))
          ) : (
            <p className="recent-empty">
              Your investigations will
              <br />
              appear here.
            </p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="sample-card">
            <div className="sample-icon">
              <Beaker size={18} />
              <span>MEET YOUR DEBUGGING AGENT</span>
            </div>
            <h3>Start with a real failure.</h3>
            <p>Explore a Python project with reproducible bugs.</p>
            <button onClick={() => void loadDemo()} disabled={busy !== null}>
              {busy === "demo" ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                "Explore sample project"
              )}
              <ArrowUpRight size={14} />
            </button>
          </div>
          <div className="sidebar-footer">
            <span className="profile-avatar">D</span>
            <span>
              <strong>Developer</strong>
              <small>Local environment</small>
            </span>
            <span className="local-lock">
              <ShieldCheck size={17} />
            </span>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              onClick={() => setMobileNav(true)}
            >
              <Menu size={20} />
            </button>
            <span className="breadcrumb-home">
              <Command size={16} />
              Workspace
            </span>
            <ChevronRight size={14} />
            <strong>
              {view === "workspace"
                ? "Investigation"
                : view === "runtime"
                  ? "Runtime & models"
                  : formatStatus(view)}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="local-chip">
              <span className="tiny-dot green-dot" />
              LOCAL ENVIRONMENT
            </span>
            <div className="topbar-separator" />
            <span className="version">v0.1.0</span>
            <span className="header-avatar">D</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                <span className="eyebrow-dash" />
                EVIDENCE IN. ANSWERS OUT.
              </div>
              <h1>
                {view === "workspace"
                  ? "Investigation workspace"
                  : view === "projects"
                    ? "Your projects"
                    : view === "history"
                      ? "Investigation history"
                      : "Runtime & models"}
                <span className="heading-dot">.</span>
              </h1>
              <p>
                {view === "workspace"
                  ? "Connect the clues. Find the cause. Verify the fix."
                  : view === "projects"
                    ? "Bring your Python code. Keep every investigation in an isolated copy."
                    : view === "history"
                      ? "A persistent record of the evidence, decisions, and outcomes."
                      : "See what is connected and what your local environment needs."}
              </p>
            </div>
            <Button onClick={openIntake}>
              <Plus size={17} />
              New investigation
            </Button>
          </div>

          {healthError && !loading && (
            <div className="connection-banner">
              <TriangleAlert size={19} />
              <div>
                <strong>Backend connection unavailable</strong>
                <span>{healthError}</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void refreshHealth();
                  void refreshCollections();
                }}
              >
                <RefreshCw size={14} />
                Retry
              </Button>
            </div>
          )}
          {view === "workspace" && (
            <>
              <div className="runtime-strip">
                <div>
                  <span
                    className={cn(
                      "tiny-dot",
                      ready ? "green-dot" : health ? "amber-dot" : "",
                    )}
                  />
                  <strong>
                    {loading
                      ? "Connecting to your local environment"
                      : ready
                        ? "Your investigation environment is ready"
                        : health
                          ? "Some runtime dependencies need attention"
                          : "Waiting for the API connection"}
                  </strong>
                  <span className="runtime-strip-description">
                    {ready
                      ? "Runs locally. Changes stay in your sandbox."
                      : "Evidence collection remains available when connected."}
                  </span>
                </div>
                <button onClick={() => navigate("runtime")}>
                  View runtime
                  <ArrowUpRight size={13} />
                </button>
              </div>
              <section
                className="metrics-grid"
                aria-label="Investigation overview"
              >
                <Metric
                  icon={FolderGit2}
                  label="PROJECT FILES"
                  value={activeProject ? String(activeProject.file_count) : "—"}
                  detail={investigation?.project_name || "No project selected"}
                  color="lime"
                />
                <Metric
                  icon={FileSearch}
                  label="EVIDENCE COLLECTED"
                  value={
                    investigation ? String(investigation.evidence.length) : "—"
                  }
                  detail={
                    investigation
                      ? "Observed source artifacts"
                      : "Logs, source & tracebacks"
                  }
                  color="purple"
                />
                <Metric
                  icon={Network}
                  label="ROOT-CAUSE HYPOTHESES"
                  value={
                    investigation
                      ? String(investigation.hypotheses.length)
                      : "—"
                  }
                  detail={
                    investigation?.hypotheses.length
                      ? "Ranked by supporting evidence"
                      : "Grounded in your evidence"
                  }
                  color="blue"
                />
                <Metric
                  icon={FlaskConical}
                  label="VERIFICATION"
                  value={
                    investigation?.verification
                      ? formatStatus(investigation.verification.status)
                      : "Not run"
                  }
                  detail={
                    investigation?.verification
                      ? `${investigation.verification.passed} passed · ${investigation.verification.failed} failed`
                      : "Real tests. Recorded outcomes."
                  }
                  color="peach"
                  textValue
                />
              </section>
              <div className="workspace-grid">
                <section className="investigation-panel">
                  <div className="panel-heading">
                    <div className="panel-title">
                      <span className="title-icon">
                        <CircleDot size={17} />
                      </span>
                      <h2>
                        {investigation
                          ? investigation.project_name
                          : "Active investigation"}
                      </h2>
                      {investigation ? (
                        <StatusBadge status={investigation.status} />
                      ) : (
                        <span className="quiet-badge">Ready when you are</span>
                      )}
                    </div>
                    <button
                      className="icon-button"
                      title="Refresh investigation"
                      aria-label="Refresh investigation"
                      disabled={!activeId || activeLoading}
                      onClick={() =>
                        activeId && void refreshInvestigation(activeId, true)
                      }
                    >
                      <RefreshCw
                        size={15}
                        className={activeLoading ? "spin" : ""}
                      />
                    </button>
                  </div>
                  {investigation && (
                    <div className="investigation-meta">
                      <span>
                        <GitBranch size={13} />
                        {investigation.id.slice(0, 10)}
                      </span>
                      <span>
                        <Clock3 size={13} />
                        {relativeTime(investigation.created_at)}
                      </span>
                      <span>
                        <ShieldCheck size={13} />
                        Isolated workspace
                      </span>
                    </div>
                  )}
                  <Tabs.Root value={selectedTab} onValueChange={setSelectedTab}>
                    <Tabs.List
                      className="tabs-list"
                      aria-label="Investigation detail"
                    >
                      {tabs.map(({ id, label, icon: Icon, count }) => (
                        <Tabs.Trigger
                          key={id}
                          value={id}
                          className="tab-trigger"
                        >
                          <Icon size={15} />
                          <span>{label}</span>
                          {!!count && (
                            <span className="tab-count">{count}</span>
                          )}
                        </Tabs.Trigger>
                      ))}
                    </Tabs.List>
                    <div className="tab-panels">
                      {activeLoading ? (
                        <Loading />
                      ) : (
                        <>
                          <Tabs.Content value="evidence">
                            {investigation?.error && (
                              <div className="inline-error">
                                <TriangleAlert size={16} />
                                <span>{investigation.error}</span>
                              </div>
                            )}
                            {investigation?.evidence.length ? (
                              <EvidenceList items={investigation.evidence} />
                            ) : investigation ? (
                              <EmptyState
                                icon={FileSearch}
                                title="Collecting the facts"
                                description={
                                  isRunning(investigation.status)
                                    ? "Source files, logs, and test output will appear as the agent collects them."
                                    : "No evidence has been recorded for this investigation. Check the activity feed for details."
                                }
                              />
                            ) : (
                              <Welcome
                                onStart={openIntake}
                                onDemo={() => void loadDemo()}
                                busy={busy === "demo"}
                              />
                            )}
                          </Tabs.Content>
                          <Tabs.Content value="hypotheses">
                            {investigation?.hypotheses.length ? (
                              <div className="hypotheses-list">
                                <div className="section-intro">
                                  <span className="purple-label">
                                    <Sparkles size={13} />
                                    AI REASONING
                                  </span>
                                  <p>
                                    Possible causes ranked against the collected
                                    evidence. Confidence is a model estimate.
                                  </p>
                                </div>
                                {investigation.hypotheses.map((item, index) => (
                                  <HypothesisCard
                                    key={item.id}
                                    hypothesis={item}
                                    index={index}
                                    evidence={investigation.evidence}
                                  />
                                ))}
                                {investigation.diagnostics.length > 0 && (
                                  <div className="diagnostic-observations">
                                    <span className="observed-label"><Beaker size={13} />OBSERVED DIAGNOSTIC RESULTS</span>
                                    {investigation.diagnostics.map((item, index) => (
                                      <details key={`${item.tool}-${item.path}-${index}`}>
                                        <summary><Terminal size={13} /><strong>{formatStatus(item.tool)}</strong><code>{item.path}</code><StatusBadge status={item.status} /><ChevronDown size={13} /></summary>
                                        <pre className="code-block">{item.observation}</pre>
                                      </details>
                                    ))}
                                  </div>
                                )}
                              </div>
                            ) : (
                              <EmptyState
                                icon={Network}
                                title="Follow the evidence"
                                description="Evidence-backed hypotheses will appear here after analysis. Supporting and contradicting clues stay visible."
                              />
                            )}
                          </Tabs.Content>
                          <Tabs.Content value="patch">
                            {investigation?.patch ? (
                              <PatchReview
                                investigation={investigation}
                                onApprove={() => void reviewPatch("approve")}
                                onReject={() => void reviewPatch("reject")}
                                busy={busy}
                              />
                            ) : (
                              <EmptyState
                                icon={GitCompareArrows}
                                title="A focused fix, for your review"
                                description="When the agent has enough evidence, it will propose a source diff here. Every patch requires your explicit approval."
                              />
                            )}
                          </Tabs.Content>
                          <Tabs.Content value="tests">
                            <TestComparison
                              baseline={investigation?.baseline || null}
                              verification={investigation?.verification || null}
                            />
                          </Tabs.Content>
                          <Tabs.Content value="report">
                            {investigation ? (
                              <ReportPanel investigation={investigation} />
                            ) : (
                              <EmptyState
                                icon={BookOpen}
                                title="The full story, documented"
                                description="Your investigation report brings together observations, hypotheses, decisions, and actual verification results."
                              />
                            )}
                          </Tabs.Content>
                        </>
                      )}
                    </div>
                  </Tabs.Root>
                  <div className="panel-footnote">
                    <ShieldCheck size={13} />
                    <span>
                      Source code is analyzed locally. Patches require your
                      approval.
                    </span>
                    <span className="footnote-decor">✳</span>
                  </div>
                </section>
                <ActivityPanel
                  events={events}
                  status={investigation?.status}
                  streamState={streamState}
                />
              </div>
              <div className="bottom-info">
                <span>
                  <Box size={14} />
                  Isolated by design
                </span>
                <span>
                  <CheckCheck size={14} />
                  Evidence before conclusions
                </span>
                <span>
                  <GitCompareArrows size={14} />
                  You approve every change
                </span>
                <span className="bottom-info-end">Built for the why.</span>
              </div>
            </>
          )}

          {view === "projects" && (
            <section className="projects-view">
              <div className="section-toolbar">
                <span>
                  {projects.length} imported{" "}
                  {projects.length === 1 ? "project" : "projects"}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void loadDemo()}
                  disabled={busy !== null}
                >
                  {busy === "demo" ? (
                    <LoaderCircle size={14} className="spin" />
                  ) : (
                    <Beaker size={14} />
                  )}
                  Import sample project
                </Button>
              </div>
              {loading ? (
                <Loading label="Loading projects" />
              ) : projects.length ? (
                <div className="project-grid">
                  {projects.map((project) => (
                    <article className="project-card" key={project.id}>
                      <span className="project-card-icon">
                        <FolderGit2 size={24} />
                      </span>
                      <h2>{project.name}</h2>
                      <p>
                        <FileCode2 size={14} />
                        {project.file_count} files<span>·</span>
                        {relativeTime(project.created_at)}
                      </p>
                      <div className="project-card-footer">
                        <span>
                          <ShieldCheck size={13} />
                          Isolated copy
                        </span>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => {
                            setProjectId(project.id);
                            setIntakeMode("existing");
                            setFormError("");
                            setDialogOpen(true);
                          }}
                        >
                          Investigate
                          <ArrowRight size={14} />
                        </Button>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="standalone-panel">
                  <EmptyState
                    icon={FolderGit2}
                    title="Your next answer starts here"
                    description="Import a local Python directory or ZIP archive, or explore the bundled sample with reproducible failures."
                  >
                    <Button onClick={openIntake}>
                      <Plus size={16} />
                      Import a project
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => void loadDemo()}
                      disabled={busy !== null}
                    >
                      <Beaker size={16} />
                      Try sample project
                    </Button>
                  </EmptyState>
                </div>
              )}
              <div className="info-note">
                <Info size={16} />
                Projects are copied into managed workspaces. Tests run only
                inside restricted Docker containers.
              </div>
            </section>
          )}

          {view === "history" && (
            <section className="history-view">
              <div className="section-toolbar">
                <span>
                  {history.length}{" "}
                  {history.length === 1 ? "investigation" : "investigations"}
                </span>
                <div className="search-input">
                  <Search size={15} />
                  <input
                    placeholder="Filter investigations…"
                    aria-label="Filter investigations"
                    value={historyQuery}
                    onChange={(event) => setHistoryQuery(event.target.value)}
                  />
                  {historyQuery && (
                    <button
                      aria-label="Clear filter"
                      onClick={() => setHistoryQuery("")}
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              </div>
              {loading ? (
                <Loading label="Loading history" />
              ) : history.length ? (
                <div className="history-table">
                  <div className="history-table-head">
                    <span>PROJECT / INVESTIGATION</span>
                    <span>STATUS</span>
                    <span>STARTED</span>
                    <span />
                  </div>
                  {history
                    .filter((item) =>
                      `${item.project_name} ${item.id} ${item.status}`
                        .toLowerCase()
                        .includes(historyQuery.toLowerCase()),
                    )
                    .map((item) => (
                      <button
                        key={item.id}
                        className="history-row"
                        onClick={() => selectInvestigation(item.id)}
                      >
                        <div className="history-project">
                          <span className="history-icon">
                            <FolderGit2 size={19} />
                          </span>
                          <span>
                            <strong>{item.project_name}</strong>
                            <small>{item.id.slice(0, 12)}</small>
                          </span>
                        </div>
                        <StatusBadge status={item.status} />
                        <time
                          title={new Date(item.created_at).toLocaleString()}
                        >
                          {relativeTime(item.created_at)}
                        </time>
                        <ArrowUpRight size={17} />
                      </button>
                    ))}
                  {!history.filter((item) =>
                    `${item.project_name} ${item.id} ${item.status}`
                      .toLowerCase()
                      .includes(historyQuery.toLowerCase()),
                  ).length && (
                    <p className="no-matches">
                      No investigations match “{historyQuery}”.
                    </p>
                  )}
                </div>
              ) : (
                <div className="standalone-panel">
                  <EmptyState
                    icon={History}
                    title="A clear record of every investigation"
                    description="Start your first investigation to build a history of observations, proposed repairs, and verified outcomes."
                  >
                    <Button onClick={openIntake}>
                      <Plus size={16} />
                      New investigation
                    </Button>
                  </EmptyState>
                </div>
              )}
            </section>
          )}

          {view === "runtime" && (
            <RuntimeView
              health={health}
              error={healthError}
              loading={loading}
              onRefresh={() => {
                void refreshHealth();
                notify("Refreshing local runtime status.");
              }}
            />
          )}
        </main>
        <footer className="page-footer">
          <span className="footer-brand">
            <Asterisk size={14} />
            rootcause.ai
          </span>
          <span>Less guesswork. More understanding.</span>
          <span className="footer-local">
            <span className="tiny-dot green-dot" />
            LOCAL WORKSPACE
          </span>
        </footer>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (busy !== "start") setDialogOpen(open);
        }}
        title="Let's get to the root cause."
        description="Choose a Python project and add the clues you already have."
      >
        <form onSubmit={(event) => void startInvestigation(event)}>
          <Tabs.Root value={intakeMode} onValueChange={setIntakeMode}>
            <Tabs.List className="intake-tabs" aria-label="Project source">
              {projects.length > 0 && (
                <Tabs.Trigger value="existing">
                  <FolderGit2 size={15} />
                  Existing project
                </Tabs.Trigger>
              )}
              <Tabs.Trigger value="directory">
                <Folder size={15} />
                Local directory
              </Tabs.Trigger>
              <Tabs.Trigger value="archive">
                <Upload size={15} />
                ZIP archive
              </Tabs.Trigger>
            </Tabs.List>
            <div className="intake-source">
              <Tabs.Content value="existing">
                <label className="form-label" htmlFor="project-select">
                  PROJECT
                </label>
                <select
                  id="project-select"
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                  required={intakeMode === "existing"}
                >
                  <option value="" disabled>
                    Select a project
                  </option>
                  {projects.map((project) => (
                    <option value={project.id} key={project.id}>
                      {project.name} · {project.file_count} files
                    </option>
                  ))}
                </select>
              </Tabs.Content>
              <Tabs.Content value="directory">
                <label className="form-label" htmlFor="project-directory">
                  ABSOLUTE DIRECTORY PATH
                </label>
                <div className="input-icon">
                  <Folder size={17} />
                  <input
                    id="project-directory"
                    placeholder="C:\Projects\my-python-app"
                    value={directory}
                    onChange={(event) => setDirectory(event.target.value)}
                    required={intakeMode === "directory"}
                    autoComplete="off"
                  />
                </div>
                <p className="form-help">
                  A local directory accessible to the backend. The original
                  project stays untouched.
                </p>
              </Tabs.Content>
              <Tabs.Content value="archive">
                <label className="file-drop" htmlFor="project-archive">
                  <span className="upload-icon">
                    <Upload size={22} />
                  </span>
                  <strong>
                    {archive ? archive.name : "Choose a Python project archive"}
                  </strong>
                  <span>
                    {archive
                      ? `${(archive.size / 1024).toFixed(1)} KB · Click to change`
                      : "ZIP format · Paths and contents are validated"}
                  </span>
                  <input
                    id="project-archive"
                    type="file"
                    accept=".zip,application/zip"
                    onChange={(event) =>
                      setArchive(event.target.files?.[0] || null)
                    }
                    required={intakeMode === "archive"}
                  />
                </label>
              </Tabs.Content>
            </div>
          </Tabs.Root>
          <div className="logs-field">
            <label className="form-label" htmlFor="project-logs">
              LOGS & ERROR CONTEXT<span>Optional</span>
            </label>
            <textarea
              id="project-logs"
              placeholder={
                "Paste a traceback, failing request, or error log…\n\nThe agent also collects evidence from your project."
              }
              value={logs}
              onChange={(event) => setLogs(event.target.value)}
              rows={5}
            />
            <p className="form-help">
              Review logs for secrets before submitting. Sensitive patterns are
              redacted before AI analysis.
            </p>
          </div>
          <div className="intake-security">
            <ShieldCheck size={17} />
            <span>
              Tests run in a restricted Docker sandbox. You review every
              proposed patch before it is applied.
            </span>
          </div>
          {formError && (
            <div className="inline-error" role="alert">
              <TriangleAlert size={17} />
              <span>{formError}</span>
            </div>
          )}
          <div className="dialog-footer">
            <Button
              variant="ghost"
              type="button"
              onClick={() => setDialogOpen(false)}
              disabled={busy === "start"}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                busy !== null ||
                (intakeMode === "existing" && !projectId) ||
                (intakeMode === "directory" && !directory.trim()) ||
                (intakeMode === "archive" && !archive)
              }
            >
              {busy === "start" ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <Play size={15} fill="currentColor" />
              )}
              {busy === "start"
                ? "Starting investigation…"
                : "Start investigation"}
              <ArrowRight size={16} />
            </Button>
          </div>
        </form>
      </Dialog>
      {notice && (
        <div
          className={cn("toast", `toast-${notice.type}`)}
          role={notice.type === "error" ? "alert" : "status"}
        >
          {notice.type === "error" ? (
            <TriangleAlert size={18} />
          ) : notice.type === "success" ? (
            <CheckCircle2 size={18} />
          ) : (
            <Info size={18} />
          )}
          <span>{notice.message}</span>
          <button
            onClick={() => setNotice(null)}
            aria-label="Dismiss notification"
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  detail,
  color,
  textValue,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  color: string;
  textValue?: boolean;
}) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
        <span className={`metric-icon icon-${color}`}>
          <Icon size={17} strokeWidth={1.7} />
        </span>
      </div>
      <div className={cn("metric-value", textValue && "metric-value-text")}>
        {value}
      </div>
      <p title={detail}>{detail}</p>
    </article>
  );
}

function Welcome({
  onStart,
  onDemo,
  busy,
}: {
  onStart: () => void;
  onDemo: () => void;
  busy: boolean;
}) {
  return (
    <div className="welcome-state">
      <div className="investigation-graphic" aria-hidden="true">
        <div className="graphic-ring ring-one" />
        <div className="graphic-ring ring-two" />
        <div className="graphic-ring ring-three" />
        <span className="graphic-node node-code">
          <Braces size={18} />
        </span>
        <span className="graphic-node node-log">
          <Terminal size={17} />
        </span>
        <span className="graphic-node node-test">
          <FlaskConical size={17} />
        </span>
        <span className="graphic-center">
          <Asterisk size={38} strokeWidth={1.3} />
        </span>
        <span className="graphic-spark spark-one" />
        <span className="graphic-spark spark-two" />
        <span className="graphic-label label-source">source.py</span>
        <span className="graphic-label label-trace">traceback.log</span>
      </div>
      <span className="welcome-eyebrow">
        A LITTLE CONTEXT. A LOT MORE CLARITY.
      </span>
      <h2>
        Every failure has a story.
        <br />
        <span>Let's find yours.</span>
      </h2>
      <p>
        Turn scattered logs, source code, and failing tests
        <br className="desktop-break" /> into an evidence-backed path to a fix.
      </p>
      <div className="welcome-actions">
        <Button onClick={onStart}>
          <Plus size={16} />
          Start investigation
          <ArrowRight size={16} />
        </Button>
        <button className="text-button" onClick={onDemo} disabled={busy}>
          {busy ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Beaker size={16} />
          )}
          Try a sample project
        </button>
      </div>
      <div className="welcome-steps">
        <span>
          <span>01</span>Collect evidence
        </span>
        <ChevronRight size={12} />
        <span>
          <span>02</span>Find the cause
        </span>
        <ChevronRight size={12} />
        <span>
          <span>03</span>Verify the fix
        </span>
      </div>
    </div>
  );
}

function EvidenceList({ items }: { items: Evidence[] }) {
  const [filter, setFilter] = useState("all");
  const kinds = [...new Set(items.map((item) => item.kind))];
  const filtered =
    filter === "all" ? items : items.filter((item) => item.kind === filter);
  return (
    <div className="evidence-list">
      <div className="evidence-toolbar">
        <span className="observed-label">
          <CircleDot size={13} />
          OBSERVED FACTS
        </span>
        <label>
          <ListFilter size={14} />
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            aria-label="Filter evidence type"
          >
            <option value="all">All evidence</option>
            {kinds.map((kind) => (
              <option key={kind} value={kind}>
                {formatStatus(kind)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {filtered.map((item, index) => (
        <details className="evidence-card" key={item.id} open={index === 0}>
          <summary>
            <span
              className={cn(
                "evidence-file-icon",
                item.kind.includes("log") || item.kind.includes("trace")
                  ? "icon-peach"
                  : "icon-purple",
              )}
            >
              {item.kind.includes("log") || item.kind.includes("trace") ? (
                <Terminal size={17} />
              ) : (
                <FileCode2 size={17} />
              )}
            </span>
            <span className="evidence-source">
              <strong>
                {item.path || formatStatus(item.kind)}
                {item.line ? (
                  <span className="line-number">:{item.line}</span>
                ) : null}
              </strong>
              <small>
                {formatStatus(item.kind)}
                <span>·</span>
                {relativeTime(item.observed_at)}
              </small>
            </span>
            <span className="evidence-id">E{items.indexOf(item) + 1}</span>
            <ChevronDown size={15} />
          </summary>
          <pre className="code-block evidence-code">{item.content}</pre>
        </details>
      ))}
    </div>
  );
}

function HypothesisCard({
  hypothesis,
  index,
  evidence,
}: {
  hypothesis: Hypothesis;
  index: number;
  evidence: Evidence[];
}) {
  const confidence = safeConfidence(hypothesis.confidence);
  return (
    <article className="hypothesis-card">
      <div className="hypothesis-heading">
        <span className="rank">{String(index + 1).padStart(2, "0")}</span>
        <h3>{hypothesis.title}</h3>
        <span className="confidence-value">
          {confidence}%<small>confidence</small>
        </span>
      </div>
      <div className="confidence-bar">
        <span style={{ width: `${confidence}%` }} />
      </div>
      <p className="hypothesis-reasoning">{hypothesis.reasoning}</p>
      <div className="hypothesis-evidence">
        <span>
          <CheckCircle2 size={14} />
          {hypothesis.supporting_evidence.length} supporting
        </span>
        <span>
          <Circle size={13} />
          {hypothesis.contradicting_evidence.length} contradicting
        </span>
      </div>
      {hypothesis.supporting_evidence.length > 0 && (
        <div className="evidence-chips">
          {hypothesis.supporting_evidence.map((id) => {
            const item = evidence.find((entry) => entry.id === id);
            return (
              <span key={id} title={item?.path || id}>
                <FileText size={11} />
                {item
                  ? `E${evidence.indexOf(item) + 1} · ${item.path || formatStatus(item.kind)}`
                  : id}
              </span>
            );
          })}
        </div>
      )}
      {hypothesis.diagnostic_checks.length > 0 && (
        <details className="diagnostic-details">
          <summary>
            <Beaker size={13} />
            Diagnostic checks
            <ChevronDown size={13} />
          </summary>
          <pre>
            {hypothesis.diagnostic_checks
              .map((item) =>
                typeof item === "string" ? item : JSON.stringify(item, null, 2),
              )
              .join("\n")}
          </pre>
        </details>
      )}
    </article>
  );
}

function PatchReview({
  investigation,
  onApprove,
  onReject,
  busy,
}: {
  investigation: Investigation;
  onApprove: () => void;
  onReject: () => void;
  busy: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const patch = investigation.patch!;
  const reviewable =
    investigation.status === "awaiting_approval" &&
    !["applied", "rejected", "approved"].includes(patch.status);
  const copyDiff = async () => {
    try {
      await navigator.clipboard.writeText(patch.diff);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="patch-view">
      <div
        className={cn(
          "patch-callout",
          reviewable ? "" : "patch-callout-neutral",
        )}
      >
        <span className="patch-callout-icon">
          {reviewable ? (
            <GitCompareArrows size={21} />
          ) : (
            <ShieldCheck size={21} />
          )}
        </span>
        <div>
          <strong>
            {reviewable
              ? "Your review is the next step."
              : `Patch ${formatStatus(patch.status).toLowerCase()}`}
          </strong>
          <p>
            {reviewable
              ? "Inspect the diff below. Approval applies it to the isolated copy and starts real verification tests."
              : "The proposed diff is preserved as part of this investigation."}
          </p>
        </div>
      </div>
      {patch.explanation && <p className="patch-explanation">{patch.explanation}</p>}
      <div className="diff-container">
        <div className="diff-toolbar">
          <span>
            <GitCompareArrows size={14} />
            {patch.edits.length} {patch.edits.length === 1 ? "file" : "files"}{" "}
            changed
          </span>
          <button
            className="icon-button"
            onClick={() => void copyDiff()}
            aria-label="Copy proposed diff"
            title="Copy diff"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
        <div
          className="diff-code"
          role="region"
          aria-label="Proposed code changes"
          tabIndex={0}
        >
          {patch.diff ? (
            patch.diff.split("\n").map((line, index) => (
              <div
                key={index}
                className={cn(
                  "diff-line",
                  line.startsWith("+") && !line.startsWith("+++") && "diff-add",
                  line.startsWith("-") &&
                    !line.startsWith("---") &&
                    "diff-remove",
                  line.startsWith("@@") && "diff-section",
                )}
              >
                <span className="diff-line-number">{index + 1}</span>
                <code>{line || " "}</code>
              </div>
            ))
          ) : (
            <pre>No textual diff was returned.</pre>
          )}
        </div>
      </div>
      {reviewable && (
        <div className="patch-actions">
          <span>
            <ShieldCheck size={14} />
            Your original project stays untouched.
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={busy !== null}
            onClick={onReject}
          >
            {busy === "reject" ? (
              <LoaderCircle size={14} className="spin" />
            ) : (
              <X size={14} />
            )}
            Reject
          </Button>
          <Button size="sm" disabled={busy !== null} onClick={onApprove}>
            {busy === "approve" ? (
              <LoaderCircle size={14} className="spin" />
            ) : (
              <Check size={15} />
            )}
            Approve & verify
          </Button>
        </div>
      )}
    </div>
  );
}

function TestComparison({
  baseline,
  verification,
}: {
  baseline: TestResult | null;
  verification: TestResult | null;
}) {
  return (
    <div className="tests-view">
      <div className="section-intro">
        <span className="observed-label">
          <FlaskConical size={13} />
          ACTUAL EXECUTION RESULTS
        </span>
        <p>
          Tests execute in restricted Docker containers. A fix is verified only
          when the recorded test results support it.
        </p>
      </div>
      <div className="test-comparison-grid">
        <TestSummary
          title="Baseline"
          subtitle="BEFORE PATCH"
          result={baseline}
        />
        <TestSummary
          title="Verification"
          subtitle="AFTER APPROVAL"
          result={verification}
        />
      </div>
      {[baseline, verification].some(Boolean) ? (
        <div className="test-outputs">
          {baseline && <TestOutput title="Baseline output" result={baseline} />}
          {verification && (
            <TestOutput title="Verification output" result={verification} />
          )}
        </div>
      ) : (
        <div className="tests-waiting">
          <ShieldCheck size={18} />
          <p>
            No tests have run yet. Baseline and verification results appear here
            after actual execution.
          </p>
        </div>
      )}
    </div>
  );
}

function TestSummary({
  title,
  subtitle,
  result,
}: {
  title: string;
  subtitle: string;
  result: TestResult | null;
}) {
  return (
    <article className="test-summary">
      <div className="test-summary-top">
        <span>{subtitle}</span>
        {result ? (
          <StatusBadge status={result.status} />
        ) : (
          <span className="quiet-badge">Not run</span>
        )}
      </div>
      <h3>{title}</h3>
      <div className="test-numbers">
        <span className="test-pass">
          <strong>{result ? result.passed : "—"}</strong>passed
        </span>
        <span className="test-fail">
          <strong>{result ? result.failed : "—"}</strong>failed
        </span>
        <span>
          <strong>{result ? result.errors : "—"}</strong>errors
        </span>
        <span>
          <strong>{result ? result.skipped : "—"}</strong>skipped
        </span>
      </div>
      <div className="test-summary-bottom">
        <span>
          <Clock3 size={12} />
          {result
            ? `${result.duration_seconds.toFixed(2)}s`
            : "Awaiting execution"}
        </span>
        {result && <span>exit {result.exit_code ?? "—"}</span>}
      </div>
    </article>
  );
}

function TestOutput({ title, result }: { title: string; result: TestResult }) {
  return (
    <details
      className="test-output"
      open={result.failed > 0 || result.errors > 0}
    >
      <summary>
        <Terminal size={15} />
        <strong>{title}</strong>
        <span>{result.tests.length} collected tests</span>
        <ChevronDown size={15} />
      </summary>
      {result.tests.length > 0 && (
        <div className="test-cases">
          {result.tests.map((test, index) => (
            <div key={`${test.nodeid}-${index}`}>
              {test.outcome === "passed" ? (
                <CheckCircle2 size={13} className="text-green" />
              ) : test.outcome === "failed" ? (
                <XCircle size={13} className="text-red" />
              ) : (
                <Circle size={13} />
              )}
              <code>{test.nodeid}</code>
              <span className={`text-${statusTone(test.outcome)}`}>
                {test.outcome}
              </span>
            </div>
          ))}
        </div>
      )}
      <pre className="code-block">
        {result.stdout || "(No standard output)"}
        {result.stderr ? `\n\nSTDERR\n${result.stderr}` : ""}
      </pre>
    </details>
  );
}

function ReportPanel({ investigation }: { investigation: Investigation }) {
  const verified =
    ["verified", "completed"].includes(investigation.status) &&
    investigation.verification?.status === "passed";
  return (
    <div className="report-view">
      <div className="report-icon">
        <FileText size={28} strokeWidth={1.4} />
      </div>
      <span className="observed-label">INVESTIGATION RECORD</span>
      <h3>From the first clue to the final test.</h3>
      <p>
        {investigation.summary ||
          "This report captures the current investigation, including observed evidence, ranked hypotheses, patch decisions, and recorded test outcomes."}
      </p>
      <div className="report-facts">
        <div>
          <span>Project</span>
          <strong>{investigation.project_name}</strong>
        </div>
        <div>
          <span>Investigation status</span>
          <StatusBadge status={investigation.status} />
        </div>
        <div>
          <span>Evidence artifacts</span>
          <strong>{investigation.evidence.length}</strong>
        </div>
        <div>
          <span>Verification outcome</span>
          <strong className={verified ? "text-green" : ""}>
            {verified
              ? "Verified by recorded tests"
              : investigation.verification
                ? formatStatus(investigation.verification.status)
                : "Not verified"}
          </strong>
        </div>
      </div>
      <Button asChild>
        <a
          href={`/api/investigations/${encodeURIComponent(investigation.id)}/report`}
          download
        >
          <ArrowDownToLine size={16} />
          Download report
          <ArrowUpRight size={15} />
        </a>
      </Button>
      <span className="report-format">
        MARKDOWN · INCLUDES CURRENT RECORDED RESULTS
      </span>
    </div>
  );
}

function ActivityPanel({
  events,
  status,
  streamState,
}: {
  events: InvestigationEvent[];
  status?: string;
  streamState: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoscroll, setAutoscroll] = useState(true);
  useEffect(() => {
    if (autoscroll && scrollRef.current)
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [events.length, autoscroll]);
  return (
    <aside className="activity-panel">
      <div className="panel-heading">
        <div className="panel-title">
          <Activity size={17} />
          <h2>Agent activity</h2>
        </div>
        {streamState === "connected" ? (
          <span className="live-badge">
            <span />
            LIVE
          </span>
        ) : (
          <span className="activity-idle">
            {streamState === "reconnecting"
              ? "RECONNECTING"
              : streamState === "connecting"
                ? "CONNECTING"
                : status
                  ? "RECORDED"
                  : "STANDBY"}
          </span>
        )}
      </div>
      <div className="activity-description">
        <span className="agent-avatar">
          <Asterisk size={16} />
        </span>
        <span>A transparent trail of every step.</span>
      </div>
      <div
        className="activity-stream"
        ref={scrollRef}
        onScroll={(event) => {
          const target = event.currentTarget;
          setAutoscroll(
            target.scrollHeight - target.scrollTop - target.clientHeight < 70,
          );
        }}
      >
        {events.length ? (
          <ol className="activity-events">
            {events.map((event, index) => {
              const error = /error|fail|blocked/.test(event.type);
              const success = /complete|verified|passed/.test(event.type);
              return (
                <li key={`${event.id}-${index}`}>
                  <span
                    className={cn(
                      "event-marker",
                      error && "event-error",
                      success && "event-success",
                    )}
                  >
                    {error ? (
                      <TriangleAlert size={11} />
                    ) : success ? (
                      <Check size={11} />
                    ) : (
                      <Circle size={7} fill="currentColor" />
                    )}
                  </span>
                  <div>
                    <div className="event-heading">
                      <strong>{formatStatus(event.type)}</strong>
                      <time>
                        {new Date(event.created_at).toLocaleTimeString(
                          undefined,
                          { hour: "2-digit", minute: "2-digit", hour12: false },
                        )}
                      </time>
                    </div>
                    <p>{event.message}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <div className="activity-empty">
            <div className="activity-empty-graphic">
              <span />
              <span />
              <span />
              <Terminal size={23} />
            </div>
            <h3>No activity just yet</h3>
            <p>
              Start an investigation to follow
              <br />
              the agent's reasoning and actions
              <br />
              as they happen.
            </p>
            <span className="activity-waiting">
              <span className="tiny-dot" />
              Waiting for an investigation
            </span>
          </div>
        )}
      </div>
      <div className="activity-footer">
        <span className={cn("tiny-dot", isRunning(status) && "green-dot")} />
        {isRunning(status)
          ? "Investigation in progress"
          : status === "awaiting_approval"
            ? "Awaiting your patch decision"
            : events.length
              ? `${events.length} recorded events`
              : "Every action. Fully traceable."}
        <span className="activity-footer-symbol">
          <Terminal size={13} />
        </span>
      </div>
    </aside>
  );
}

function RuntimeView({
  health,
  error,
  loading,
  onRefresh,
}: {
  health: RuntimeHealth | null;
  error: string;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="runtime-view">
      <div className="section-toolbar">
        <span>LOCAL SERVICE CONNECTIONS</span>
        <Button variant="secondary" size="sm" onClick={onRefresh}>
          <RefreshCw size={14} />
          Refresh status
        </Button>
      </div>
      {loading ? (
        <Loading label="Checking runtime" />
      ) : (
        <>
          <div className="runtime-cards">
            <article className="runtime-card">
              <div className="runtime-card-heading">
                <span className="runtime-service-icon icon-purple">
                  <Sparkles size={24} />
                </span>
                <span
                  className={cn(
                    "status-badge",
                    health?.ai.available ? "tone-green" : "tone-amber",
                  )}
                >
                  <span className="status-dot" />
                  {health?.ai.available ? "Connected" : "Unavailable"}
                </span>
              </div>
              <h2>Ollama · Gemma</h2>
              <p>
                Evidence-grounded analysis through your configured local AI
                provider.
              </p>
              <dl>
                <div>
                  <dt>Configured model</dt>
                  <dd>
                    <code>{health?.ai.model || "Not reported"}</code>
                  </dd>
                </div>
                <div>
                  <dt>Available models</dt>
                  <dd>
                    {health?.ai.models.length
                      ? health.ai.models.map((model) => (
                          <span className="model-tag" key={model}>
                            {model}
                          </span>
                        ))
                      : "None detected"}
                  </dd>
                </div>
              </dl>
              {health?.ai.error && (
                <div className="runtime-error">
                  <TriangleAlert size={15} />
                  <span>{health.ai.error}</span>
                </div>
              )}
            </article>
            <article className="runtime-card">
              <div className="runtime-card-heading">
                <span className="runtime-service-icon icon-blue">
                  <Box size={24} />
                </span>
                <span
                  className={cn(
                    "status-badge",
                    health?.sandbox.available ? "tone-green" : "tone-amber",
                  )}
                >
                  <span className="status-dot" />
                  {health?.sandbox.available ? "Available" : "Unavailable"}
                </span>
              </div>
              <h2>Docker sandbox</h2>
              <p>
                Real test execution inside a restricted, isolated container.
              </p>
              <dl>
                <div>
                  <dt>Sandbox image</dt>
                  <dd>
                    <code>{health?.sandbox.image || "Not reported"}</code>
                  </dd>
                </div>
                <div>
                  <dt>Execution policy</dt>
                  <dd>Non-root · No network · Resource limits</dd>
                </div>
              </dl>
              {health?.sandbox.error && (
                <div className="runtime-error">
                  <TriangleAlert size={15} />
                  <span>{health.sandbox.error}</span>
                </div>
              )}
            </article>
          </div>
          {error && (
            <div className="inline-error">
              <TriangleAlert size={17} />
              <span>{error}</span>
            </div>
          )}
          <div className="runtime-principles">
            <span className="runtime-service-icon icon-lime">
              <ShieldCheck size={24} />
            </span>
            <div>
              <h3>Local by default. Explicit by design.</h3>
              <p>
                RootCause AI never runs imported project code directly on the
                host. Model output is treated as untrusted, diagnostic commands
                are restricted, and source patches need your approval. Missing
                services are reported as blockers; they never produce simulated
                results.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
