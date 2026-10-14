import json

import fleet


def write_transcript(tmp_path, entries):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries))
    return path


def assistant(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def tool_use(tid, name, **params):
    return {"type": "tool_use", "id": tid, "name": name, "input": params}


def tool_result(tid):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tid}]},
    }


def digest(tmp_path, monkeypatch, entries):
    path = write_transcript(tmp_path, entries)
    monkeypatch.setattr(fleet, "transcript_path", lambda _sid: str(path))
    return fleet.transcript_digest_uncached("sid")


def test_inflight_agents_exclude_finished(tmp_path, monkeypatch):
    out = digest(
        tmp_path,
        monkeypatch,
        [
            assistant(tool_use("a1", "Task", subagent_type="Explore")),
            assistant(tool_use("a2", "Task", subagent_type="Plan")),
            tool_result("a1"),  # a1 came back, a2 is still running
        ],
    )
    assert out["agents"] == ["Plan"]


def test_no_agents_when_all_returned(tmp_path, monkeypatch):
    out = digest(
        tmp_path,
        monkeypatch,
        [assistant(tool_use("a1", "Task", subagent_type="Explore")), tool_result("a1")],
    )
    assert out["agents"] == []


def test_agent_falls_back_to_description(tmp_path, monkeypatch):
    out = digest(
        tmp_path,
        monkeypatch,
        [assistant(tool_use("a1", "Task", description="audit deps"))],
    )
    assert out["agents"] == ["audit deps"]


def test_title_is_latest_real_user_message(tmp_path, monkeypatch):
    out = digest(
        tmp_path,
        monkeypatch,
        [
            {"type": "user", "message": {"content": "first ask"}},
            {
                "type": "user",
                "message": {"content": "<system-reminder>ignored</system-reminder>"},
            },
            {
                "type": "user",
                "message": {"content": [{"type": "text", "text": "second ask"}]},
            },
            {
                "type": "user",
                "isSidechain": True,
                "message": {"content": "subagent chatter"},
            },
        ],
    )
    assert out["title"] == "second ask"


def test_activity_label_reflects_recent_tools(tmp_path, monkeypatch):
    out = digest(
        tmp_path, monkeypatch, [assistant(tool_use("b1", "Bash", command="ls"))]
    )
    assert out["doing"] == "shell"

    # Task outranks Bash: subagents are the more interesting signal.
    out = digest(
        tmp_path,
        monkeypatch,
        [
            assistant(
                tool_use("b1", "Bash"), tool_use("a1", "Task", subagent_type="Explore")
            )
        ],
    )
    assert out["doing"] == "agents"


def test_topic_icon_describes_the_subject():
    assert fleet.topic_icon("Security survey L6: ML IP inventory") == "🔒"
    assert fleet.topic_icon("tmux mouse scroll + copy") == "🖥"
    assert fleet.topic_icon("inframon queue per-runner PR") == "🏗"
    assert fleet.topic_icon("") == "●"  # nothing to go on


def test_missing_transcript_is_empty(monkeypatch):
    monkeypatch.setattr(fleet, "transcript_path", lambda _sid: "")
    assert fleet.transcript_digest_uncached("sid") == fleet.EMPTY_DIGEST


def test_malformed_lines_are_skipped(tmp_path, monkeypatch):
    path = tmp_path / "t.jsonl"
    path.write_text('not json\n{"type":"user","message":{"content":"kept"}}\n')
    monkeypatch.setattr(fleet, "transcript_path", lambda _sid: str(path))
    assert fleet.transcript_digest_uncached("sid")["title"] == "kept"


def test_chrome_filter_drops_claude_code_furniture():
    noise = [
        "❯\xa0update the artifact with that",  # suggested next message
        "⏵⏵ auto mode on (shift+tab to cycle) · ← for agents",
        "↳ Scheduled ML-fleet reset check",
        "⧉  owner_checklist · dashboard",
        "new task? /clear to save 612.8k tokens",
        "─" * 80,
        "  ~/w/x | repo:sam/b +733-0 | Opus 5 | 12% ctx | 5h 23%",
    ]
    assert all(fleet.is_chrome(line) for line in noise)

    content = [
        "✻ Worked for 33s · done 10:58 AM",
        "  We can't reuse GitHub OIDC for the hosts.",
        "├──────────┼──────────┤",  # a table rule is content, not furniture
        "⏺ Bash(ruff format pytools/fleet.py)",
    ]
    assert not any(fleet.is_chrome(line) for line in content)
