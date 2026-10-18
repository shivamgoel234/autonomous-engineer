import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  Code2,
  Download,
  FileCode2,
  GitBranch,
  GitCompareArrows,
  LoaderCircle,
  Play,
  Plus,
  ShieldCheck,
  Square,
  Terminal,
  X,
} from "lucide-react";
import { api, streamEvents } from "./api";
import type { AgentEvent, Health, Project, Run } from "./types";
import { terminal } from "./types";

const tasks: Record<string, string> = {
  cart: "Fix calculate_total: include item quantities and reject discounts outside 0..1.",
  slug: "Fix slugify to collapse whitespace, strip surrounding spaces, and lowercase text.",
  median:
    "Fix median: sort without mutating input, average even-length middles, reject empty.",
};
const label = (value: string) => value.replaceAll("_", " ");

export default function App() {
  const [token, setToken] = useState("");
  const [tokenDraft, setTokenDraft] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState("");
  const [source, setSource] = useState("");
  const [task, setTask] = useState("");
  const [tab, setTab] = useState<"activity" | "diff" | "tests" | "source">(
    "activity",
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const owner = health?.role === "owner";
  const active = !!run && !terminal.has(run.status);
  const latestTest = run?.tests.at(-1);

  async function action(work: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }
  async function connect() {
    await action(async () => {
      const h = await api<Health>("/health", tokenDraft);
      const [p, r] = await Promise.all([
        api<Project[]>("/projects", tokenDraft),
        api<Run[]>("/runs", tokenDraft),
      ]);
      setHealth(h);
      setToken(tokenDraft);
      setTokenDraft("");
      setProjects(p);
      setRuns(r);
      const first = p[0] ?? null;
      setProject(first);
      if (first) setTask(tasks[first.kind.split(":")[1]] ?? "");
    });
  }
  function chooseProject(p: Project) {
    setProject(p);
    setTask(tasks[p.kind.split(":")[1]] ?? "");
    setRun(null);
    setEvents([]);
  }
  async function addDemo(scenario: string) {
    await action(async () => {
      const p = await api<Project>(`/projects/demo/${scenario}`, token, {
        method: "POST",
      });
      setProjects((prev) => [p, ...prev]);
      chooseProject(p);
    });
  }
  async function start() {
    if (!project) return;
    await action(async () => {
      const created = await api<Run>("/runs", token, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ project_id: project.id, task }),
      });
      setRun(created);
      setRuns((prev) => [created, ...prev]);
      setEvents([]);
      setTab("activity");
    });
  }
  async function review(decision: "approved" | "rejected") {
    if (!run) return;
    await action(async () => {
      const reviewed = await api<Run>(`/runs/${run.id}/review`, token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      setRun(reviewed);
      setRuns((prev) =>
        prev.map((item) => (item.id === reviewed.id ? reviewed : item)),
      );
    });
  }
  async function download() {
    if (!run) return;
    await action(async () => {
      const response = await fetch(`/api/v1/runs/${run.id}/patch`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Patch export requires approval");
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "agent.patch";
      a.click();
      URL.revokeObjectURL(url);
    });
  }
  useEffect(() => {
    if (!project || !token) return;
    const controller = new AbortController();
    api<string[]>(`/projects/${project.id}/files`, token, {
      signal: controller.signal,
    })
      .then((list) => {
        setFiles(list);
        setSelectedFile(
          list.find((f) => f.startsWith("src/") && f.endsWith("solution.py")) ??
            list[0] ??
            "",
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [project?.id, token]);
  useEffect(() => {
    if (!project || !selectedFile) return;
    const controller = new AbortController();
    api<{ content: string }>(
      `/projects/${project.id}/file?path=${encodeURIComponent(selectedFile)}`,
      token,
      { signal: controller.signal },
    )
      .then((item) => setSource(item.content))
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [project?.id, selectedFile, token]);
  useEffect(() => {
    if (!run?.id) return;
    const controller = new AbortController();
    const id = run.id;
    let timer: ReturnType<typeof setTimeout>;
    let cursor = 0;
    setEvents([]);
    async function observe() {
      try {
        await streamEvents(id, token, cursor, controller.signal, (event) => {
          cursor = event.id;
          setEvents((prev) =>
            prev.some((e) => e.id === event.id) ? prev : [...prev, event],
          );
        });
      } catch (e) {
        if (!controller.signal.aborted) timer = setTimeout(observe, 1500);
      }
    }
    async function poll() {
      try {
        const updated = await api<Run>(`/runs/${id}`, token, {
          signal: controller.signal,
        });
        setRun(updated);
        setRuns((prev) => prev.map((r) => (r.id === id ? updated : r)));
        if (!terminal.has(updated.status) && !controller.signal.aborted)
          pollTimer = setTimeout(poll, 700);
      } catch (e) {
        if (!controller.signal.aborted) pollTimer = setTimeout(poll, 1500);
      }
    }
    let pollTimer: ReturnType<typeof setTimeout>;
    void observe();
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
      clearTimeout(pollTimer);
    };
  }, [run?.id, token]);

  if (!health)
    return (
      <main className="welcome">
        <div className="welcome-grid" />
        <div className="welcome-content">
          <div className="brand">
            <Code2 size={24} />
            <span>
              forge<span className="brand-dot">.</span>
            </span>
          </div>
          <p className="eyebrow">AUTONOMOUS SOFTWARE ENGINEER / V1.0</p>
          <h1>
            From failing test
            <br />
            to a <em>reviewable patch.</em>
          </h1>
          <p className="intro">
            An observable engineering agent. Inspect a repository, make a
            bounded change, verify it, and stay in control.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void connect();
            }}
          >
            <label htmlFor="token">Workspace access token</label>
            <div className="connect">
              <input
                id="token"
                type="password"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                placeholder="Paste your ASE_OWNER_TOKEN"
                required
                autoComplete="off"
              />
              <button disabled={busy}>
                {busy ? (
                  <LoaderCircle className="spin" size={18} />
                ) : (
                  <ArrowUpRight size={18} />
                )}{" "}
                Connect
              </button>
            </div>
          </form>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="welcome-features">
            <span>
              <ShieldCheck size={16} /> Policy-controlled tools
            </span>
            <span>
              <GitCompareArrows size={16} /> Human-reviewed changes
            </span>
            <span>
              <Terminal size={16} /> Test evidence
            </span>
          </div>
          <p className="setup-note">
            Start the backend first. Your token stays in memory for this
            session.
          </p>
        </div>
      </main>
    );

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Code2 size={23} />
          <span>
            forge<span className="brand-dot">.</span>
          </span>
          <small>WORKSPACE</small>
        </div>
        <div className="nav-item">
          <GitBranch size={17} /> Engineering runs <span>{runs.length}</span>
        </div>
        <div className="side-heading">REPOSITORIES</div>
        {projects.map((p) => (
          <button
            className={`repo ${project?.id === p.id ? "selected" : ""}`}
            key={p.id}
            onClick={() => chooseProject(p)}
          >
            <span className="repo-icon">
              <Code2 size={16} />
            </span>
            <span>
              {p.name}
              <small>
                {p.kind.startsWith("demo:")
                  ? "Bundled Python fixture"
                  : "Uploaded Python repository"}
              </small>
            </span>
          </button>
        ))}
        {!projects.length && (
          <p className="muted side-text">Choose a sample below to begin.</p>
        )}
        {owner && (
          <div className="examples">
            <div className="side-heading">START WITH A SAMPLE</div>
            {[
              ["cart", "Checkout total"],
              ["slug", "URL slug"],
              ["median", "Median edge cases"],
            ].map(([id, name]) => (
              <button disabled={busy} key={id} onClick={() => void addDemo(id)}>
                <Plus size={14} />
                {name}
              </button>
            ))}
          </div>
        )}
        {owner && health.provider === "openai" && (
          <>
            <button
              className="upload"
              onClick={() => uploadRef.current?.click()}
              disabled={busy}
            >
              <Plus size={15} /> Upload source ZIP
            </button>
            <input
              hidden
              type="file"
              ref={uploadRef}
              accept=".zip"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                void action(async () => {
                  const p = await api<Project>(
                    `/projects/upload?name=${encodeURIComponent(f.name)}`,
                    token,
                    {
                      method: "POST",
                      body: f,
                      headers: { "Content-Type": "application/zip" },
                    },
                  );
                  setProjects((prev) => [p, ...prev]);
                  chooseProject(p);
                });
                e.target.value = "";
              }}
            />
          </>
        )}
        <div className="side-heading">RECENT RUNS</div>
        <div className="run-list">
          {runs.slice(0, 8).map((r) => (
            <button
              key={r.id}
              className={run?.id === r.id ? "current" : ""}
              onClick={() => {
                setRun(r);
                setProject(projects.find((p) => p.id === r.project_id) ?? null);
                setTask(r.task);
                setTab("activity");
              }}
            >
              <span
                className={`status-dot ${r.status === "approved" || r.status === "awaiting_review" ? "green" : ""}`}
              />
              <span>
                {r.task.slice(0, 29)}
                <small>
                  {label(r.status)} · {r.id.slice(0, 6)}
                </small>
              </span>
            </button>
          ))}
        </div>
        <div className="side-footer">
          <span className="avatar">{owner ? "O" : "R"}</span>
          <div>
            {owner ? "Workspace owner" : "Patch reviewer"}
            <small>Local engineering workspace</small>
          </div>
          <button
            title="Disconnect"
            onClick={() => {
              setHealth(null);
              setToken("");
              setRun(null);
            }}
          >
            <X size={15} />
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            Workspace <ChevronRight size={14} />{" "}
            <strong>{project?.name ?? "Getting started"}</strong>
          </div>
          <span className="connection">
            <span className="status-dot green" /> API connected
          </span>
        </header>
        <div className="page-head">
          <div>
            <p className="eyebrow">ENGINEERING WORKSPACE</p>
            <h1>
              Every change. <span>Verified.</span>
            </h1>
            <p>Explore the code, follow the reasoning, review the evidence.</p>
          </div>
          <div className="mode-tag">
            <ShieldCheck size={17} />
            <div>
              {health.provider === "demo" ? "Scripted demo" : "OpenAI agent"}
              <small>
                {health.runner === "docker"
                  ? "Docker execution"
                  : "Trusted fixtures · local execution"}
              </small>
            </div>
          </div>
        </div>
        {health.provider === "demo" && (
          <div className="notice">
            <span className="notice-label">LEARNING MODE</span> The demo uses
            predefined repairs and runs real tests. It does not call an AI
            model.
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        <section className="task-card">
          <div className="section-title">
            <span className="number">01</span>
            <h2>Define the task</h2>
            <span className="python-tag">PYTHON</span>
          </div>
          <label className="sr-only" htmlFor="task">
            Engineering task
          </label>
          <textarea
            id="task"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            readOnly={health.provider === "demo" || !owner}
            placeholder="Choose a sample repository, or upload a ZIP in OpenAI mode…"
          />
          <div className="task-footer">
            <span>
              <ShieldCheck size={14} /> Protected tests · 3 attempts · 18 tool
              calls
            </span>
            <button
              className="primary"
              disabled={
                !project || !owner || busy || active || task.length < 10
              }
              onClick={() => void start()}
            >
              {active ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <Play size={15} />
              )}{" "}
              {active ? "Agent running" : "Start engineering run"}
            </button>
          </div>
        </section>
        <div className="metrics">
          <div>
            <span>RUN STATUS</span>
            <strong
              className={
                run?.status === "awaiting_review" || run?.status === "approved"
                  ? "positive"
                  : ""
              }
            >
              {run ? label(run.status) : "Ready to start"}
            </strong>
          </div>
          <div>
            <span>REPAIR ATTEMPTS</span>
            <strong>
              {run?.attempt ?? "—"}
              <small> / 3</small>
            </strong>
          </div>
          <div>
            <span>LATEST TESTS</span>
            <strong>
              {latestTest ? `${latestTest.passed} passed` : "—"}
              <small>
                {latestTest
                  ? ` / ${latestTest.failed + latestTest.errors} failed`
                  : ""}
              </small>
            </strong>
          </div>
          <div>
            <span>TOKENS USED</span>
            <strong>
              {run
                ? (run.input_tokens + run.output_tokens).toLocaleString()
                : "—"}
            </strong>
          </div>
          <div>
            <span>ELAPSED</span>
            <strong>{run ? `${run.elapsed_seconds}s` : "—"}</strong>
          </div>
        </div>
        <div className="workbench">
          <section className="file-panel">
            <div className="panel-heading">
              <FileCode2 size={15} />
              <h2>Repository</h2>
              <span>{files.length}</span>
            </div>
            <p className="file-caption">Original snapshot</p>
            {files.map((file) => (
              <button
                className={selectedFile === file ? "file active-file" : "file"}
                key={file}
                onClick={() => {
                  setSelectedFile(file);
                  setTab("source");
                }}
              >
                <FileCode2 size={14} />
                <span>{file}</span>
                {run?.changed_files.includes(file) && (
                  <span className="modified">M</span>
                )}
              </button>
            ))}
            {!files.length && (
              <p className="muted side-text">No repository selected</p>
            )}
            <div className="boundary">
              <ShieldCheck size={16} />
              <strong>Bounded by design</strong>
              <p>
                Source edits only. Acceptance tests stay immutable. Your
                original snapshot stays intact.
              </p>
            </div>
          </section>
          <section className="activity-panel">
            <div className="tabs">
              {(
                [
                  ["activity", "Activity"],
                  ["diff", "Patch diff"],
                  ["tests", "Test results"],
                  ["source", "Source"],
                ] as const
              ).map(([id, name]) => (
                <button
                  className={tab === id ? "active-tab" : ""}
                  key={id}
                  onClick={() => setTab(id)}
                >
                  {name}
                  {id === "diff" && run?.changed_files.length ? (
                    <span>{run.changed_files.length}</span>
                  ) : null}
                </button>
              ))}
              {active && owner && (
                <button
                  className="cancel"
                  onClick={() =>
                    void action(async () => {
                      await api(`/runs/${run!.id}/cancel`, token, {
                        method: "POST",
                      });
                    })
                  }
                >
                  <Square size={12} /> Cancel
                </button>
              )}
            </div>
            <div className="panel-content">
              {tab === "activity" && (
                <>
                  {run?.plan && (
                    <div className="plan">
                      <h3>Implementation plan</h3>
                      {run.plan.map((step, i) => (
                        <p key={i}>
                          <span>{i + 1}</span>
                          {step}
                        </p>
                      ))}
                    </div>
                  )}
                  {events.length ? (
                    <div className="timeline">
                      {events.map((event) => (
                        <div
                          className={`event ${event.kind === "validated" ? "event-success" : ""}`}
                          key={event.id}
                        >
                          <span className="event-symbol">
                            {event.kind === "validated" ? (
                              <Check size={13} />
                            ) : event.kind === "test" ? (
                              <Terminal size={13} />
                            ) : (
                              <span />
                            )}
                          </span>
                          <div>
                            <strong>{event.message}</strong>
                            <small>
                              {new Date(event.created_at).toLocaleTimeString()}{" "}
                              <span>· {event.kind}</span>
                              {typeof event.data.path === "string" &&
                                ` · ${event.data.path}`}
                            </small>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty">
                      <div className="empty-icon">
                        <GitBranch size={28} />
                      </div>
                      <h3>Your next patch starts here.</h3>
                      <p>
                        Select a repository and start a run.
                        <br />
                        The agent's tool calls and test evidence will appear
                        here.
                      </p>
                      <span>
                        PLAN <ChevronRight size={12} /> INSPECT{" "}
                        <ChevronRight size={12} /> REPAIR{" "}
                        <ChevronRight size={12} /> VERIFY
                      </span>
                    </div>
                  )}
                </>
              )}
              {tab === "source" && (
                <>
                  <div className="code-caption">
                    {selectedFile || "No file selected"}{" "}
                    <span>Original · read only</span>
                  </div>
                  <pre className="code">{source}</pre>
                </>
              )}
              {tab === "diff" &&
                (run?.diff ? (
                  <>
                    <div className="code-caption">
                      Unified patch{" "}
                      <span>{run.changed_files.length} file(s) changed</span>
                    </div>
                    <pre className="diff">
                      {run.diff.split("\n").map((line, i) => (
                        <span
                          className={
                            line.startsWith("+")
                              ? "addition"
                              : line.startsWith("-")
                                ? "deletion"
                                : line.startsWith("@@")
                                  ? "hunk"
                                  : ""
                          }
                          key={i}
                        >
                          {line}
                          {"\n"}
                        </span>
                      ))}
                    </pre>
                  </>
                ) : (
                  <div className="empty">
                    <GitCompareArrows size={28} />
                    <h3>No patch yet</h3>
                    <p>A proposed diff appears after verification.</p>
                  </div>
                ))}
              {tab === "tests" &&
                (run?.tests.length ? (
                  <div className="test-history">
                    {run.tests.map((test, i) => (
                      <details key={i} open={i === run.tests.length - 1}>
                        <summary>
                          <span
                            className={
                              test.exit_code === 0 ? "test-pass" : "test-fail"
                            }
                          >
                            {test.exit_code === 0 ? (
                              <Check size={14} />
                            ) : (
                              <X size={14} />
                            )}
                          </span>
                          {test.attempt === 0
                            ? "Baseline"
                            : `Attempt ${test.attempt}`}
                          <span>
                            {test.passed} passed · {test.failed} failed ·{" "}
                            {test.errors} errors · {test.skipped} skipped
                          </span>
                        </summary>
                        <pre className="test-log">{test.output}</pre>
                      </details>
                    ))}
                  </div>
                ) : (
                  <div className="empty">
                    <Terminal size={28} />
                    <h3>Evidence before confidence.</h3>
                    <p>Baseline and repair test results will appear here.</p>
                  </div>
                ))}
            </div>
            {run?.error && <div className="run-error">{run.error}</div>}
            {run?.status === "awaiting_review" && (
              <div className="review-bar">
                <div>
                  <ShieldCheck size={19} />
                  <span>
                    <strong>Patch ready for review</strong>
                    <small>
                      Passing acceptance tests support this patch. Review the
                      diff before exporting.
                    </small>
                  </span>
                </div>
                <button onClick={() => void review("rejected")} disabled={busy}>
                  Reject
                </button>
                <button
                  className="primary"
                  onClick={() => void review("approved")}
                  disabled={busy}
                >
                  <Check size={15} /> Approve patch
                </button>
              </div>
            )}
            {run?.status === "approved" && (
              <div className="review-bar">
                <div>
                  <Check size={19} />
                  <strong>Approved for manual application</strong>
                </div>
                <button className="primary" onClick={() => void download()}>
                  <Download size={15} /> Download patch
                </button>
              </div>
            )}
          </section>
        </div>
        <footer className="page-footer">
          <span>FORGE / AUTONOMOUS SOFTWARE ENGINEER</span>
          <span>Observable. Bounded. Human reviewed.</span>
        </footer>
      </main>
    </div>
  );
}
