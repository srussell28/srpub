#!/usr/bin/env python3
"""CT-dash: a local web view of every ct/tmux Claude session.

Serves one page that merges `claude agents --json` (status), tmux (previews and
the tty each session is attached to), git (repo/branch) and gh (PRs). Clicking a
row focuses that session's terminal tab.

    fleet.py [--port 7447] [--host 127.0.0.1] [--open]

Bind to 0.0.0.0 to reach it from a phone over a VPN; that requires --token.
"""

import argparse
import contextlib
import glob
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from srutils import fetch_prs

try:  # optional: without it, cards keep the free heuristic line
    import anthropic
except ImportError:
    anthropic = None

HERE = Path(__file__).resolve().parent
# Set while at least one page is streaming. Everything expensive waits on it,
# so an unwatched service costs nothing but an idle socket.
VIEWERS = threading.Event()
POLL_FAST = 2  # a visible tab
POLL_SLOW = 20  # a tab that is open but hidden
PR_SECONDS = 300  # gh is slow and rate-limited, so refresh it rarely
PREVIEW_LINES = 30  # the page clips to fit; send enough to fill a tall card
PREVIEW_COLS = 160  # cap a wrapped line's share of the card
LOCAL_NAME = "ct-dash.localhost"
# 8787 is RStudio Server's default and 8888 is Jupyter's; 7447 collides with
# neither, and sits below the ephemeral range the OS allocates from.
DEFAULT_PORT = int(os.environ.get("CT_DASH_PORT") or 7447)
# A bulk worker summarizing many sessions, so the cheap model; override to taste.
AI_MODEL = os.environ.get("CT_DASH_MODEL") or "claude-haiku-4-5"
AI_SECONDS = 120  # one batched call, and only for sessions that changed


def source_rev() -> str:
    """Changes whenever this app's own source does, so --dev can reload."""
    try:
        return str(max(os.path.getmtime(HERE / f) for f in ("fleet.py", "fleet.html")))
    except OSError:
        return "0"


def sh(args, cwd=None, timeout=10) -> str:
    """Run a command, returning stdout or "" — never raising."""
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def repo_and_branch(path: str) -> tuple:
    """(repo, branch) for a worktree, repo being the shared checkout's name."""
    common = sh(["git", "-C", path, "rev-parse", "--git-common-dir"])
    if not common:
        return "", ""
    root = Path(common if os.path.isabs(common) else os.path.join(path, common))
    repo = root.resolve().parent.name
    return repo, sh(["git", "-C", path, "branch", "--show-current"])


def claude_sessions() -> dict:
    """Claude's own view of its sessions, keyed by cwd."""
    raw = sh(["claude", "agents", "--json"], timeout=15)
    if not raw.startswith("["):
        return {}
    try:
        return {s["cwd"]: s for s in json.loads(raw) if s.get("cwd")}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def tmux_clients() -> dict:
    """session name -> tty of its most recently active client."""
    out = sh(
        [
            "tmux",
            "list-clients",
            "-F",
            "#{client_session}\t#{client_tty}\t#{client_activity}",
        ]
    )
    best = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        name, tty, activity = parts
        if name not in best or activity > best[name][1]:
            best[name] = (tty, activity)
    return {k: v[0] for k, v in best.items()}


RULE_CHARS = "─━—–-_=·.*#"


def is_chrome(line: str) -> bool:
    """Claude Code's own furniture, which the card already says better."""
    text = line.strip()
    if len(text) >= 8 and len(set(text)) <= 2 and text[0] in RULE_CHARS:
        return True  # a horizontal rule
    # "❯ ..." is the prompt box, which holds a SUGGESTED next message — showing
    # it reads as something that was said. "⧉" is the artifact tab strip, which
    # the chips already cover.
    if text.startswith(("❯", "⏵⏵", "↳ ", "⧉")):
        return True
    if "/clear to save" in text:
        return True  # context hint
    # our own status line: "~/path | repo:branch | Model | NN% ctx | 5h NN%"
    return " | " in text and ("% ctx" in text or "5h " in text)


BG_SHELLS = re.compile(r"(\d+) shells? still running")


def pane(session: str) -> dict:
    """One capture, giving both the preview lines and what is running in the background."""
    out = sh(["tmux", "capture-pane", "-p", "-t", session])
    shells = 0
    for found in BG_SHELLS.finditer(out):
        shells = max(shells, int(found.group(1)))
    lines = [
        line.rstrip()[:PREVIEW_COLS]
        for line in out.splitlines()
        if line.strip() and not is_chrome(line)
    ]
    return {"preview": lines[-PREVIEW_LINES:], "bg_shells": shells}


_TRANSCRIPTS = {}  # sessionId -> path, so we glob once per session


def transcript_path(session_id) -> str:
    """The session's JSONL, or "" if it has not been written yet."""
    if not session_id:
        return ""
    if session_id not in _TRANSCRIPTS:
        hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
        _TRANSCRIPTS[session_id] = hits[0] if hits else ""
    return _TRANSCRIPTS[session_id]


# The icon describes what a session is ABOUT, matched against its topic.
# First hit wins, so order these most-specific-first.
TOPIC_ICONS = [
    ("🔒", ("security", "vuln", "secret", "credential", "auth", " key", "ip protect")),
    ("☁️", ("aws", "gcp", "azure", "cloud", "s3", "ec2", "iam")),
    ("🧠", ("inference", "model", "ml ", "train", "fp16", "quant", "prune", "embed")),
    ("🏗", ("infra", "runner", "fleet", "deploy", "ci ", "pipeline", "queue", "bazel")),
    ("🐛", ("bug", "fix", "crash", "overflow", "hang", "leak", "regression", "debug")),
    ("⚡", ("perf", "latency", "speed", "optimi", "cache", "reuse", "bench")),
    ("🖥", ("tmux", "terminal", "statusline", "shell", "bashrc", "dash", "ui ", "css")),
    ("🔍", ("search", "survey", "audit", "investigat", "analy", "verif")),
    ("📦", ("image", "docker", "package", "release", "build", "push")),
    ("📝", ("doc", "readme", "write-up", "notes", "plan", "memo")),
    ("🧪", ("test", "golden", "eval", "coverage")),
    ("🔀", ("merge", "rebase", "branch", "worktree", "pr ", "review")),
]


# The verb for what Claude is doing right now, from its most recent tool.
# "running" rather than "shell": the latter reads like the BACKGROUND state,
# which is also about shells but means the opposite (nothing in the foreground).
ACTIVITY = [
    ("Task", "agents"),
    ("AskUserQuestion", "asking"),
    ("WebFetch", "browsing"),
    ("WebSearch", "browsing"),
    ("Edit", "editing"),
    ("Write", "writing"),
    ("Grep", "searching"),
    ("Glob", "searching"),
    ("Read", "reading"),
    ("Bash", "running"),
]


def topic_icon(topic: str) -> str:
    """An icon for the subject of the work, not the tool being used."""
    text = f" {topic.lower()} "
    for glyph, words in TOPIC_ICONS:
        if any(word in text for word in words):
            return glyph
    return "●"


_DIGESTS = {}  # sessionId -> (mtime, digest)
_AGENTS = {}  # sessionId -> {tool_use_id: name}, so a long agent is not forgotten
FIRST_SCAN_LINES = 20000  # a subagent can run for hours; find its launch
TAIL_LINES = 800
_ARTIFACTS = {}  # sessionId -> {url: {name, version}}, kept across digests
EMPTY_DIGEST = {"agents": [], "title": "", "doing": "", "artifacts": []}
ARTIFACT_URL = re.compile(r"https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9._-]+")


def remember_artifact(session_id, name, result):
    """Record an artifact a session published, from the Artifact tool's result.

    Accumulated rather than recomputed: a publish scrolls out of the transcript
    tail long before the artifact stops being worth a link.
    """
    text = result if isinstance(result, str) else json.dumps(result or "")
    match = ARTIFACT_URL.search(text)
    if not match:
        return
    version = re.search(r"\(Version (\d+)\)", text)
    _ARTIFACTS.setdefault(session_id, {})[match.group(0)] = {
        "url": match.group(0),
        "name": name or "artifact",
        "version": int(version.group(1)) if version else None,
    }


def transcript_digest(session_id) -> dict:
    """transcript_digest_uncached, re-read only when the transcript has grown."""
    path = transcript_path(session_id)
    if not path:
        return EMPTY_DIGEST
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return EMPTY_DIGEST
    cached = _DIGESTS.get(session_id)
    if cached and cached[0] == stamp:
        return cached[1]
    digest = transcript_digest_uncached(session_id)
    _DIGESTS[session_id] = (stamp, digest)
    return digest


def transcript_digest_uncached(session_id) -> dict:
    """One tail of the transcript, yielding what the UI needs to describe a session.

    `claude agents --json` only reports top-level sessions, so a session merely
    waiting on its subagents looks identical to one doing its own work. Pairing
    Task tool_use ids against tool_result ids separates them. The same pass picks
    up the latest request and recent tool mix for a title and icon.
    """
    path = transcript_path(session_id)
    if not path:
        return EMPTY_DIGEST
    started = dict(_AGENTS.get(session_id, {}))  # carry agents seen earlier
    finished, tools, last_user = set(), [], ""
    artifact_names = {}  # tool_use id -> a human name for what was published
    # Scan deep the first time: a Task launched hours ago is long out of the tail.
    depth = TAIL_LINES if session_id in _AGENTS else FIRST_SCAN_LINES
    for line in sh(["tail", "-n", str(depth), path], timeout=20).splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") or {}
        content = message.get("content")
        if entry.get("type") == "user" and not entry.get("isSidechain"):
            text = content if isinstance(content, str) else ""
            if isinstance(content, list):
                text = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            text = " ".join(text.split())
            if text and not text.startswith("<"):
                last_user = text
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tools.append(block.get("name"))
                params = block.get("input") or {}
                if block.get("name") in ("Task", "Agent"):
                    started[block.get("id")] = (
                        params.get("subagent_type")
                        or params.get("description")
                        or "agent"
                    )
                elif block.get("name") == "Artifact":
                    artifact_names[block.get("id")] = (
                        params.get("title") or Path(params.get("file_path") or "").stem
                    )
            elif block.get("type") == "tool_result":
                finished.add(block.get("tool_use_id"))
                if block.get("tool_use_id") in artifact_names:
                    remember_artifact(
                        session_id,
                        artifact_names[block["tool_use_id"]],
                        block.get("content"),
                    )

    # The most recent tool, not a favourite among the last few: an older call
    # would describe something the session has long since moved on from.
    doing = dict(ACTIVITY).get(tools[-1], "") if tools else ""
    live = {tid: n for tid, n in started.items() if tid not in finished}
    _AGENTS[session_id] = live
    return {
        "agents": list(live.values()),
        "title": last_user[:110],
        "doing": doing,
        "artifacts": sorted(
            _ARTIFACTS.get(session_id, {}).values(), key=lambda a: a["name"]
        ),
    }


def path_of_sid(session_id) -> str:
    return transcript_path(session_id)


def quiet_for(session_id) -> int:
    """Seconds since Claude last wrote to this session's transcript."""
    path = transcript_path(session_id)
    if not path:
        return -1
    try:
        return int(time.time() - os.path.getmtime(path))
    except OSError:
        return -1


def last_active(transcript: str, tmux_activity: str) -> int:
    """Most recent sign of life, in epoch ms.

    tmux records terminal output; the transcript records Claude writing. Either
    can be the newer one, so take whichever moved last.
    """
    stamps = []
    if transcript:
        try:
            stamps.append(os.path.getmtime(transcript) * 1000)
        except OSError:
            pass
    if tmux_activity and tmux_activity.isdigit():
        stamps.append(int(tmux_activity) * 1000)
    return int(max(stamps)) if stamps else 0


# Only "waiting" jumps the queue. busy/idle flip on every turn, and sorting on
# them (or on last activity) makes the grid reshuffle while you are reading it.
def sort_key(row) -> tuple:
    return (0 if row["status"] == "waiting" else 1, row["started_at"] or 0)


def collect(prs_by_path: dict, summaries: dict | None = None) -> list:
    """One row per tmux session, worst-first."""
    agents = claude_sessions()
    clients = tmux_clients()
    rows = []
    out = sh(
        [
            "tmux",
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_path}\t#{session_activity}",
        ]
    )
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0]:
            continue
        name, path, activity = parts
        agent = agents.get(path, {})
        repo, branch = repo_and_branch(path)
        sid = agent.get("sessionId")
        digest = transcript_digest(sid)
        topic = topic_for(sid)
        screen = pane(name)
        rows.append(
            {
                "session": name,
                "path": path,
                "repo": repo,
                "branch": branch,
                "status": agent.get("status", ""),
                # Claude last wrote this many seconds ago. A busy session that
                # has not written in a while is parked on a background job, not
                # actively working.
                "quiet_for": quiet_for(sid),
                "waiting_for": agent.get("waitingFor", ""),
                "started_at": agent.get("startedAt"),
                "last_active": last_active(path_of_sid(sid), activity),
                # The session's own topic wins; the transcript is the fallback.
                "topic": topic or digest["title"],
                "topic_source": "session" if topic else "transcript",
                "icon": topic_icon(topic or digest["title"]),
                "doing": digest["doing"],
                "agents": digest["agents"],
                "artifacts": digest["artifacts"],
                "attached": name in clients,
                "prs": prs_by_path.get(path, []),
                "ai": (summaries or {}).get(name, ""),
                "preview": screen["preview"],
                "bg_shells": screen["bg_shells"],
            }
        )
    rows.sort(key=sort_key)
    return rows


def topic_for(session_id) -> str:
    """The one-line topic a session keeps in its scratchpad, if any."""
    if not session_id:
        return ""
    base = Path(f"/tmp/claude-{os.getuid()}")
    for path in base.glob(f"*/{session_id}/scratchpad/topic"):
        try:
            return path.read_text().strip().splitlines()[0][:90]
        except (OSError, IndexError):
            return ""
    return ""


def tmux_session_names() -> set:
    out = sh(["tmux", "list-sessions", "-F", "#{session_name}"])
    return {line.strip() for line in out.splitlines() if line.strip()}


def attach(session: str) -> bool:
    """Open a new Terminal tab attached to a session nothing is watching."""
    if not shutil.which("osascript") or session not in tmux_session_names():
        return False
    # Cmd-T needs Accessibility; fall back to a new window when it is denied.
    script = f"""
    tell application "Terminal"
      activate
      try
        tell application "System Events" to keystroke "t" using command down
        delay 0.35
        do script "tmux attach -t '{session}'" in front window
      on error
        do script "tmux attach -t '{session}'"
      end try
    end tell
    return "ok"
    """
    return sh(["osascript", "-e", script], timeout=15) == "ok"


def focus(session: str) -> bool:
    """Bring the terminal tab attached to this session to the front."""
    tty = tmux_clients().get(session)
    if not tty or not shutil.which("osascript"):
        return False
    script = f'''
    tell application "Terminal"
      repeat with w in windows
        repeat with i from 1 to (count of tabs of w)
          if tty of (tab i of w) is "{tty}" then
            set selected tab of w to (tab i of w)
            set index of w to 1
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end tell
    return "no"
    '''
    return sh(["osascript", "-e", script]) == "ok"


class PRCache:
    """gh is slow, so refresh PRs on their own slow timer off the render path."""

    def __init__(self):
        self.by_path = {}
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            VIEWERS.wait()  # nobody looking: do not spend gh calls
            fresh = {}
            out = sh(
                ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_path}"]
            )
            for line in out.splitlines():
                _, _, path = line.partition("\t")
                if not path:
                    continue
                _, branch = repo_and_branch(path)
                if branch:
                    fresh[path] = fetch_prs(cwd=path, head=branch)
            self.by_path = fresh
            self._stop.wait(PR_SECONDS)


AI_PROMPT = """You are labelling a dashboard of coding sessions.

For each session write ONE short sentence saying where the work was left and what
it is now waiting on. Write it the way a colleague would answer "where is that
up to?" — e.g. "waiting for overnight tests", "waiting for PR review",
"monitoring for errors", "half way through migrating the auth tests".

Rules:
- 12 words or fewer, no trailing full stop, no session name, no preamble.
- Say what it is waiting on when it is waiting; otherwise say where it got to.
- Describe only what the transcript shows. If it is unclear, say "unclear".
"""

AI_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "summaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "session": {"type": "string"},
                        "sentence": {"type": "string"},
                    },
                    "required": ["session", "sentence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["summaries"],
        "additionalProperties": False,
    },
}


def transcript_excerpt(session_id, budget=2200) -> str:
    """A compact trace of recent turns: what was asked, done and said."""
    path = transcript_path(session_id)
    if not path:
        return ""
    parts = []
    for line in sh(["tail", "-n", "120", path], timeout=5).splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("isSidechain"):
            continue
        content = (entry.get("message") or {}).get("content")
        who = entry.get("type")
        if isinstance(content, str) and who in ("user", "assistant"):
            parts.append(f"{who}: {' '.join(content.split())[:300]}")
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and who in ("user", "assistant"):
                    parts.append(f"{who}: {' '.join(block['text'].split())[:300]}")
                elif block.get("type") == "tool_use":
                    parts.append(f"  [{block.get('name')}]")
    text = "\n".join(parts[-40:])
    return text[-budget:]


class Summarizer:
    """One batched call per cycle describing where each session was left."""

    def __init__(self):
        self.by_session = {}  # tmux session name -> sentence
        self._stamps = {}  # session name -> transcript mtime already summarized
        self.error = ""

    def available(self) -> bool:
        return bool(anthropic) and bool(os.environ.get("ANTHROPIC_API_KEY"))

    def start(self):
        if not self.available():
            self.error = "no anthropic SDK" if not anthropic else "no ANTHROPIC_API_KEY"
            print(f"[ct-dash] AI summaries off: {self.error}")
            return
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            VIEWERS.wait()  # same gate as everything else
            try:
                self.refresh()
            except Exception as e:  # noqa: BLE001 - never take the stream down
                self.error = str(e)[:120]
                print(f"[ct-dash] summary failed: {e}")
            time.sleep(AI_SECONDS)

    def _stale(self) -> list:
        """Sessions whose transcript moved since we last described them."""
        out = sh(["tmux", "list-sessions", "-F", "#{session_name}\t#{session_path}"])
        agents = claude_sessions()
        todo = []
        for line in out.splitlines():
            name, _, path = line.partition("\t")
            sid = (agents.get(path) or {}).get("sessionId")
            tpath = transcript_path(sid)
            if not name or not tpath:
                continue
            try:
                stamp = os.path.getmtime(tpath)
            except OSError:
                continue
            if self._stamps.get(name) != stamp:
                todo.append((name, sid, stamp))
        return todo

    def refresh(self):
        todo = self._stale()
        if not todo:
            return
        blocks = []
        for name, sid, _ in todo[:12]:
            excerpt = transcript_excerpt(sid)
            if excerpt:
                blocks.append(f"<session name={name!r}>\n{excerpt}\n</session>")
        if not blocks:
            return
        client = anthropic.Anthropic()
        reply = client.messages.create(
            model=AI_MODEL,
            max_tokens=1000,
            system=AI_PROMPT,
            output_config={"format": AI_SCHEMA},
            messages=[{"role": "user", "content": "\n\n".join(blocks)}],
        )
        text = next((b.text for b in reply.content if b.type == "text"), "")
        for row in json.loads(text).get("summaries", []):
            if row.get("session") and row.get("sentence"):
                self.by_session[row["session"]] = row["sentence"].strip()
        for name, _, stamp in todo:
            self._stamps[name] = stamp
        self.error = ""


class Hub:
    """Fans the latest snapshot out to every connected browser."""

    def __init__(self, prs: PRCache, ai=None):
        self.prs = prs
        self.ai = ai
        self.listeners = []
        self.lock = threading.Lock()
        self.latest = {"rows": [], "rev": source_rev()}
        self.taken_at = 0.0
        self.collects = 0

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def refresh(self):
        self.collects += 1
        self.latest = {
            "rows": collect(self.prs.by_path, self.ai.by_session if self.ai else None),
            "rev": source_rev(),
        }
        self.taken_at = time.time()
        return self.latest

    def ensure_fresh(self, max_age=5):
        """Collect on demand for a caller that is not streaming."""
        if time.time() - self.taken_at > max_age:
            self.refresh()
        return self.latest

    def _loop(self):
        while True:
            if not VIEWERS.is_set():
                VIEWERS.wait()  # park until a page connects
                continue
            try:
                self.refresh()
                self.taken_at = now = time.time()
                payload = json.dumps(self.latest)
                with self.lock:
                    for v in self.listeners:
                        if now - v["sent"] + 0.01 >= v["every"]:
                            v["sent"] = now
                            with contextlib.suppress(queue.Full):
                                v["q"].put_nowait(payload)
            except Exception as e:  # noqa: BLE001 - a bad frame must not kill the stream
                print(f"[fleet] collect failed: {e}")
            time.sleep(self.interval())

    def interval(self) -> float:
        """How often to collect: the most impatient viewer sets the pace."""
        with self.lock:
            return min((v["every"] for v in self.listeners), default=POLL_SLOW)

    def subscribe(self, every: float):
        q = queue.Queue(maxsize=4)
        with self.lock:
            self.listeners.append({"q": q, "every": every, "sent": 0.0})
            VIEWERS.set()
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.listeners = [v for v in self.listeners if v["q"] is not q]
            if not self.listeners:
                VIEWERS.clear()


def make_handler(hub: Hub, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # the default logger prints a line per poll

        def _authed(self, params) -> bool:
            return not token or params.get("token", [""])[0] == token

        def _send(self, code, body, ctype="application/json"):
            raw = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            url = urlparse(self.path)
            params = parse_qs(url.query)
            if not self._authed(params):
                return self._send(403, '{"error":"bad token"}')

            if url.path == "/":
                page = (HERE / "fleet.html").read_text()
                return self._send(200, page.replace("__TOKEN__", token), "text/html")
            if url.path == "/api/health":
                return self._send(
                    200,
                    json.dumps(
                        {
                            "collects": hub.collects,
                            "viewers": len(hub.listeners),
                            "interval": hub.interval(),
                            "age": round(time.time() - hub.taken_at, 1),
                        }
                    ),
                )
            if url.path == "/api/fleet":
                return self._send(200, json.dumps(hub.ensure_fresh()))
            if url.path == "/api/focus":
                name = params.get("session", [""])[0]
                if name in tmux_clients():
                    return self._send(
                        200, json.dumps({"ok": focus(name), "did": "focus"})
                    )
                return self._send(
                    200, json.dumps({"ok": attach(name), "did": "attach"})
                )
            if url.path == "/events":
                slow = params.get("rate", [""])[0] == "slow"
                return self._stream(POLL_SLOW if slow else POLL_FAST)
            return self._send(404, '{"error":"not found"}')

        def _stream(self, every):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = hub.subscribe(every)
            try:
                # first frame is on demand, since the loop may have been parked
                self.wfile.write(
                    f"data: {json.dumps(hub.ensure_fresh(2))}\n\n".encode()
                )
                self.wfile.flush()
                while True:
                    self.wfile.write(f"data: {q.get()}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ValueError):
                pass  # browser went away
            finally:
                hub.unsubscribe(q)

    return Handler


def _watch_source():
    """Re-exec on a source edit; the browser reconnects and reloads itself.

    Waits for the file to settle and to compile first: re-execing mid-write
    kills the server for good, since nothing is around to restart it.
    """
    start = source_rev()
    while True:
        time.sleep(1)
        if source_rev() == start:
            continue
        settled = source_rev()
        time.sleep(1.5)
        if source_rev() != settled:
            continue  # still being written
        try:
            source = (HERE / "fleet.py").read_text()
            compile(source, "fleet.py", "exec")
        except (OSError, SyntaxError) as e:
            print(f"[fleet] source does not compile, not restarting: {e}")
            start = source_rev()
            continue
        print("[fleet] source changed, restarting")
        os.execv(sys.executable, [sys.executable, *sys.argv])


SERVICE_LABEL = "ct-dash"
PLIST = Path.home() / "Library/LaunchAgents" / f"{SERVICE_LABEL}.plist"


def service_install(port: int) -> None:
    """Install a LaunchAgent so ct-dash is up after every login."""
    if sys.platform != "darwin":
        raise SystemExit(
            "ct-dash: --install-service is macOS-only (launchd). On Linux, wrap "
            "fleet.py in a systemd --user unit."
        )
    log = Path.home() / ".logs" / "ct-dash.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    # launchd starts with a bare PATH; tmux, claude and gh all live elsewhere.
    path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{SERVICE_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>{HERE / "fleet.py"}</string>
    <string>--port</string><string>{port}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
""")
    uid = os.getuid()
    sh(["launchctl", "bootout", f"gui/{uid}/{SERVICE_LABEL}"])  # ignore if absent
    out = sh(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)])
    print(f"[ct-dash] installed {PLIST}")
    print(f"[ct-dash] logs: {log}")
    print(f"[ct-dash] http://{LOCAL_NAME}:{port}/")
    if out:
        print(f"[ct-dash] launchctl: {out}")


def service_restart() -> None:
    """Reload the installed service so it picks up edited source."""
    out = sh(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{SERVICE_LABEL}"])
    print(f"[ct-dash] restarted{': ' + out if out else ''}")


def service_uninstall() -> None:
    sh(["launchctl", "bootout", f"gui/{os.getuid()}/{SERVICE_LABEL}"])
    if PLIST.exists():
        PLIST.unlink()
    print(f"[ct-dash] removed {PLIST}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", default="")
    ap.add_argument("--open", action="store_true", help="open a browser")
    ap.add_argument(
        "--dev", action="store_true", help="restart when fleet.py/fleet.html change"
    )
    ap.add_argument(
        "--install-service", action="store_true", help="run at login (launchd)"
    )
    ap.add_argument("--uninstall-service", action="store_true")
    ap.add_argument(
        "--restart-service", action="store_true", help="reload the installed service"
    )
    args = ap.parse_args()

    if args.uninstall_service:
        return service_uninstall()
    if args.restart_service:
        return service_restart()
    if args.install_service:
        return service_install(args.port)

    token = args.token
    if args.host not in ("127.0.0.1", "localhost") and not token:
        token = secrets.token_urlsafe(12)
        print(f"[fleet] non-local bind, generated token: {token}")

    if not shutil.which("tmux"):
        raise SystemExit("fleet: tmux not found — nothing to show")

    prs = PRCache()
    prs.start()
    ai = Summarizer()
    ai.start()
    hub = Hub(prs, ai)
    hub.start()

    # *.localhost resolves to loopback without any hosts entry, and a name
    # autocompletes in the browser's history where a bare IP does not.
    shown = LOCAL_NAME if args.host in ("127.0.0.1", "localhost") else args.host
    url = f"http://{shown}:{args.port}/" + (f"?token={token}" if token else "")
    print(f"[ct-dash] {url}")
    if args.open:
        webbrowser.open(url)

    if args.dev:
        threading.Thread(target=_watch_source, daemon=True).start()

    try:
        server = ThreadingHTTPServer((args.host, args.port), make_handler(hub, token))
    except OSError as e:
        raise SystemExit(
            f"ct-dash: cannot bind {args.host}:{args.port} ({e}). "
            "Another copy may be running — try --port, or CT_DASH_PORT."
        ) from e
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[fleet] bye")


if __name__ == "__main__":
    main()
