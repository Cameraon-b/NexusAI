#!/usr/bin/env python3
"""Generate NexusAI bridge response files from bridge request files.

This responder is a cognition/authoring layer only. It never posts to NexusAI,
never approves messages, and never executes commands. The scheduled
nexusai_agent_worker.py remains the only script that consumes response files and
posts replies through NexusAI's normal approval-gated API.
"""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RISK = "DOCUMENTATION ONLY"
UNKNOWN_RISK = "UNKNOWN / NEEDS REVIEW"
DEFAULT_BRIDGE_DIR = Path(__file__).resolve().parent / "bridge_queue"
INFRASTRUCTURE_TERMS = [
    "docker",
    "deploy",
    "deployment",
    "shell",
    "command",
    "powershell",
    "ssh",
    "restore",
    "delete",
    "credential",
    "credentials",
    "secret",
    "token",
    "infrastructure",
    "restart",
    "service",
    "nora",
    "bookstack",
]
READ_ONLY_TERMS = ["read-only", "readonly", "inspect", "review", "document", "documentation", "summarize", "check docs"]


@dataclass(frozen=True)
class PendingRequest:
    path: Path
    response_path: Path
    prompt_path: Path
    message_id: int
    agent: str


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_agent(agent: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent.strip())
    return cleaned or "agent"


def bridge_paths(bridge_dir: Path, message_id: int, agent: str) -> tuple[Path, Path, Path]:
    suffix = f"message-{message_id}-{safe_agent(agent)}"
    return (
        bridge_dir / f"request-{suffix}.json",
        bridge_dir / f"response-{suffix}.json",
        bridge_dir / f"prompt-{suffix}.txt",
    )


def find_pending_requests(bridge_dir: Path, agent: str, *, overwrite: bool = False) -> list[PendingRequest]:
    if not bridge_dir.exists():
        return []
    safe = safe_agent(agent)
    requests: list[PendingRequest] = []
    for path in sorted(bridge_dir.glob(f"request-message-*-{safe}.json")):
        match = re.match(r"request-message-(\d+)-", path.name)
        if not match:
            continue
        message_id = int(match.group(1))
        request_path, response_path, prompt_path = bridge_paths(bridge_dir, message_id, agent)
        if request_path != path:
            continue
        if response_path.exists() and not overwrite:
            continue
        requests.append(PendingRequest(path=request_path, response_path=response_path, prompt_path=prompt_path, message_id=message_id, agent=agent))
    return requests


def load_request(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed request JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("malformed request: root must be an object")
    if data.get("message_id") is None:
        raise ValueError("malformed request: message_id is required")
    if not str(data.get("agent") or "").strip():
        raise ValueError("malformed request: agent is required")
    return data


def compact_text(value: Any, *, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def mentions_infrastructure_change(request: dict[str, Any]) -> bool:
    # Inspect the human/original message, not the standing bridge instructions;
    # those instructions intentionally mention commands as things not to do.
    text = " ".join(str(request.get(key) or "") for key in ("subject", "body")).lower()
    if not any(term in text for term in INFRASTRUCTURE_TERMS):
        return False
    clearly_read_only = any(term in text for term in READ_ONLY_TERMS)
    actionish = any(term in text for term in ["run", "restart", "apply", "change", "delete", "restore", "deploy", "ssh", "powershell", "command", "secret", "credential"])
    return actionish or not clearly_read_only


def choose_risk(request: dict[str, Any]) -> str:
    if mentions_infrastructure_change(request):
        return UNKNOWN_RISK
    return DEFAULT_RISK


def build_template_reply(request: dict[str, Any]) -> tuple[str, str]:
    subject = compact_text(request.get("subject") or "the NexusAI message", limit=120)
    body = compact_text(request.get("body"), limit=320)
    sender = compact_text(request.get("from") or "the sender", limit=80)
    risk = choose_risk(request)

    if risk == UNKNOWN_RISK:
        reply = (
            f"Acknowledged on '{subject}'. Because this touches infrastructure or operational change, "
            "I would treat it as a proposed next step for Cameron review rather than an executed action. "
            f"My suggested reply is to clarify the requested scope, confirm it is safe/read-only if applicable, "
            f"and keep the NexusAI record tied to the original note from {sender}."
        )
    elif body:
        reply = (
            f"Acknowledged on '{subject}'. My concise take: {body} "
            "I can help turn this into a small documentation-only next step or checklist, and I will not claim any files, services, or infrastructure were changed."
        )
    else:
        reply = (
            f"Acknowledged on '{subject}'. I can help with a concise documentation-only follow-up and will keep the reply scoped to this conversation."
        )
    return reply, risk


def build_manual_prompt(request: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        You are generating a NexusAI bridge response for {request.get('agent', 'the selected agent')}.

        Write a concise reply body only. Stay within the topic and answer the message directly.
        Do not claim to execute commands. Do not claim to have changed files, services, Docker,
        BookStack, GitHub, Nora, or infrastructure unless the request explicitly says that already happened.
        If action is requested, phrase it as a proposed next step or task. Do not bypass NexusAI approval.

        Default risk level: {DEFAULT_RISK}
        Use risk level {UNKNOWN_RISK} if Docker, deploys, shell commands, PowerShell, SSH,
        restore, delete, credentials, or infrastructure changes are involved unless clearly read-only.

        Request JSON:
        {json.dumps(request, indent=2, ensure_ascii=False)}

        After drafting, create this response JSON by hand:
        {{
          "message_id": {request.get('message_id')},
          "agent": {json.dumps(request.get('agent'))},
          "reply_body": "<paste concise reply here>",
          "risk_level": "{choose_risk(request)}",
          "created_by": "{request.get('agent', 'Agent')} bridge responder",
          "ready": true
        }}
        """
    ).strip() + "\n"


def response_payload(request: dict[str, Any], reply_body: str, risk_level: str) -> dict[str, Any]:
    return {
        "message_id": int(request["message_id"]),
        "agent": str(request.get("agent") or "").strip(),
        "reply_body": reply_body.strip(),
        "risk_level": risk_level or DEFAULT_RISK,
        "created_by": f"{str(request.get('agent') or '').strip() or 'Agent'} bridge responder",
        "created_at": utc_now(),
        "ready": True,
    }


def write_response(path: Path, payload: dict[str, Any], *, overwrite: bool = False) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def process_one(args: argparse.Namespace) -> bool:
    bridge_dir = Path(args.bridge_dir)
    requests = find_pending_requests(bridge_dir, args.agent, overwrite=args.overwrite)
    if not requests:
        print(f"No pending bridge requests for {args.agent} in {bridge_dir}")
        return False

    item = requests[0]
    print(f"Bridge request: {item.path}")
    print(f"Bridge response: {item.response_path}")
    request = load_request(item.path)
    if str(request.get("agent")) != args.agent:
        raise ValueError(f"request agent {request.get('agent')!r} does not match selected agent {args.agent!r}")

    if args.mode == "manual-prompt":
        prompt = build_manual_prompt(request)
        print(prompt)
        if args.write_prompt:
            item.prompt_path.write_text(prompt, encoding="utf-8")
            print(f"Wrote prompt: {item.prompt_path}")
        print("Manual-prompt mode does not write a response JSON; paste the final response JSON manually when ready.")
        return True

    if args.mode == "template":
        reply_body, risk_level = build_template_reply(request)
        payload = response_payload(request, reply_body, risk_level)
        wrote = write_response(item.response_path, payload, overwrite=args.overwrite)
        if wrote:
            print(f"Wrote response JSON: {item.response_path}")
            print(f"Risk level: {payload['risk_level']}")
        else:
            print(f"Response already exists, not overwriting: {item.response_path}")
        return True

    raise ValueError(f"unsupported mode: {args.mode}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate one NexusAI bridge response file from one bridge request file, then exit.",
        epilog=(
            "Examples:\n"
            "  python scripts/nexusai_bridge_responder.py --agent Hermes --bridge-dir scripts/bridge_queue --mode template\n"
            "  python scripts/nexusai_bridge_responder.py --agent Hermes --bridge-dir scripts/bridge_queue --mode manual-prompt --write-prompt\n\n"
            "Safety: this script never posts to NexusAI and never executes commands."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--agent", required=True, help="Agent name to respond as, e.g. Hermes")
    parser.add_argument("--bridge-dir", default=str(DEFAULT_BRIDGE_DIR), help="Directory containing bridge request/response JSON files")
    parser.add_argument("--mode", choices=["template", "manual-prompt"], default="template", help="Responder mode")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing matching response file")
    parser.add_argument("--write-prompt", action="store_true", help="In manual-prompt mode, also write prompt-message-<id>-<agent>.txt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print("NexusAI bridge responder")
    print(f"Agent: {args.agent}")
    print(f"Bridge dir: {Path(args.bridge_dir)}")
    print(f"Mode: {args.mode}")
    print("Safety: no NexusAI posting, no approvals, no command execution.")
    process_one(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
