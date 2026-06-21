#!/usr/bin/env python3
"""Scheduled one-shot NexusAI agent worker.

Run once, process at most one approved/unread delivered message for one agent,
optionally create one reply, then exit. Safe for Windows Task Scheduler, cron,
or Hermes scheduled jobs because it never loops and never executes commands.

Bridge-file mode creates/consumes JSON handoff files under scripts/bridge_queue
so a separate human or real agent runtime can generate the reply body without
NexusAI executing anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexusai_client import request

DEFAULT_BASE_URL = "http://127.0.0.1:5055"
DEFAULT_BRIDGE_DIR = Path(__file__).resolve().parent / "bridge_queue"
DEFAULT_AUTO_REPLY = (
    "Acknowledged. I read your message. NexusAI remains a coordination, "
    "approval, messaging, and audit system only; no commands were executed."
)
AUTO_REPLY_MODES = ("ack-only", "template", "bridge-file", "agent-bridge")
BRIDGE_FALLBACKS = ("none", "template", "ack-only")
DEFAULT_RISK = "DOCUMENTATION ONLY"
UNKNOWN_RISK = "UNKNOWN / NEEDS REVIEW"
SAFETY_KEYWORDS = (
    "command", "commands", "shell", "powershell", "ssh", "docker", "compose",
    "deploy", "deployment", "restart", "restore", "system change", "state-changing",
    "approval", "approve", "approved",
)
BRIDGE_INSTRUCTIONS = [
    "Write one concise, useful reply.",
    "Stay within the topic.",
    "Do not claim to execute commands.",
    "Do not request command execution unless clearly framed as an approval request.",
    "Default to DOCUMENTATION ONLY.",
    "Do not exceed 300 words.",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_agent(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()) or "agent"


def compact_text(value: Any, max_chars: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def message_discusses_safety_topic(message: dict[str, Any]) -> bool:
    haystack = f"{message.get('subject', '')} {message.get('body', '')}".lower()
    return any(keyword in haystack for keyword in SAFETY_KEYWORDS)


def build_template_reply(message: dict[str, Any]) -> str:
    subject = compact_text(message.get("subject") or "No subject", 120)
    body = compact_text(message.get("body") or "the message", 220)
    body_fragment = re.sub(r"[.!?]+", ",", body).strip(" ,") or "the message"
    sentences = [
        f"Subject: {subject}.",
        f"I read your note: \"{body_fragment}\".",
        "My answer is to keep the next step scoped to the message topic and turn it into a clear NexusAI task or reply without claiming any work has already been performed.",
        "Next checklist item: identify the owner, desired outcome, and any approval gate before moving this forward.",
    ]
    if message_discusses_safety_topic(message):
        sentences.append("Safety: approval records permission only; it is not execution and does not execute commands or apply system changes.")
    return " ".join(sentences)


def build_auto_reply_body(message: dict[str, Any], mode: str, explicit_text: str = "") -> str:
    if mode == "ack-only":
        return explicit_text or DEFAULT_AUTO_REPLY
    if mode == "template":
        return explicit_text or build_template_reply(message)
    raise ValueError(f"Mode {mode} does not create an immediate generated reply")


def print_json(label: str, value: Any) -> None:
    print(label)
    print(json.dumps(value, indent=2, ensure_ascii=False))


def call(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    return request(method, path, payload)


def bridge_paths(bridge_dir: Path, message_id: int, agent: str) -> tuple[Path, Path]:
    name = f"message-{message_id}-{safe_agent(agent)}.json"
    return bridge_dir / f"request-{name}", bridge_dir / f"response-{name}"


def bridge_request_payload(message: dict[str, Any], agent: str) -> dict[str, Any]:
    return {
        "message_id": message.get("id"),
        "conversation_id": message.get("conversation_id"),
        "agent": agent,
        "from": message.get("from"),
        "to": message.get("to"),
        "subject": message.get("subject"),
        "body": message.get("body"),
        "risk_level": message.get("risk_level") or DEFAULT_RISK,
        "requested_at": utc_now(),
        "instructions": BRIDGE_INSTRUCTIONS,
    }


def write_bridge_request(path: Path, message: dict[str, Any], agent: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bridge_request_payload(message, agent), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def load_bridge_response(path: Path, message_id: int, agent: str) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"malformed JSON: {exc}"
    if not isinstance(data, dict):
        return None, "malformed: response root must be an object"
    if data.get("ready") is not True:
        return None, "not ready"
    if int(data.get("message_id", -1)) != int(message_id):
        return None, "malformed: message_id mismatch"
    if str(data.get("agent", "")) != agent:
        return None, "malformed: agent mismatch"
    reply_body = str(data.get("reply_body", "")).strip()
    if not reply_body:
        return None, "malformed: reply_body is required"
    if len(reply_body) > 4000:
        return None, "malformed: reply_body exceeds 4000 characters"
    data["reply_body"] = reply_body
    data["risk_level"] = str(data.get("risk_level") or DEFAULT_RISK).strip()
    return data, "ready"


def archive_bridge_files(request_path: Path, response_path: Path) -> None:
    archive_dir = request_path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "")
    for path in (request_path, response_path):
        if path.exists():
            target = archive_dir / f"{path.stem}-processed-{stamp}{path.suffix}"
            shutil.move(str(path), str(target))
            print(f"Archived bridge file: {target}")


def iter_ready_bridge_responses(bridge_dir: Path, agent: str) -> list[tuple[Path, int]]:
    if not bridge_dir.exists():
        return []
    suffix = f"-{safe_agent(agent)}.json"
    items: list[tuple[Path, int]] = []
    for path in sorted(bridge_dir.glob(f"response-message-*{suffix}")):
        match = re.match(r"response-message-(\d+)-", path.name)
        if match:
            items.append((path, int(match.group(1))))
    return items


def maybe_process_existing_bridge_response(args: argparse.Namespace) -> bool:
    if not (args.auto_reply and args.auto_reply_mode == "bridge-file"):
        return False
    bridge_dir = Path(args.bridge_dir)
    for response_path, message_id in iter_ready_bridge_responses(bridge_dir, args.agent):
        request_path, _ = bridge_paths(bridge_dir, message_id, args.agent)
        response, status = load_bridge_response(response_path, message_id, args.agent)
        print(f"Bridge response candidate: {response_path}")
        print(f"Bridge response status: {status}")
        if response is None:
            if status != "missing" and not status.startswith("not ready"):
                print("Bridge response rejected/malformed; not posting.")
            continue
        if args.dry_run:
            print(f"DRY RUN: would fetch message #{message_id}")
            print(f"DRY RUN: would post bridge reply from {response_path}")
            return True
        message = call("GET", f"/api/messages/{message_id}")
        if not isinstance(message, dict):
            print(f"Bridge response rejected: could not load message #{message_id}")
            return True
        if reply_already_exists(message, args.agent):
            print("Duplicate prevention: a reply from this agent already exists for this parent message; not posting again.")
            archive_bridge_files(request_path, response_path)
            return True
        # If the first bridge run already acknowledged the message these calls may be rejected; that is okay.
        try:
            maybe_mark_read_ack(args, message_id)
        except Exception as exc:  # noqa: BLE001
            print(f"Read/ack skipped or already complete: {exc}")
        risk_level = response.get("risk_level") or DEFAULT_RISK
        if risk_level == UNKNOWN_RISK:
            print("Bridge response risk is UNKNOWN / NEEDS REVIEW; NexusAI must require approval before delivery.")
        post_reply(args, message_id, response["reply_body"], risk_level)
        archive_bridge_files(request_path, response_path)
        return True
    return False


def reply_already_exists(message: dict[str, Any], agent: str) -> bool:
    conversation_id = message.get("conversation_id")
    message_id = message.get("id")
    if not conversation_id:
        return False
    try:
        messages = call("GET", f"/api/conversations/{conversation_id}/messages")
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not check duplicate replies: {exc}")
        return False
    if not isinstance(messages, list):
        return False
    return any(item.get("parent_message_id") == message_id and item.get("from") == agent for item in messages)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one bounded NexusAI agent inbox check, then exit.",
        epilog=(
            "Examples:\n"
            "  python scripts/nexusai_agent_worker.py --agent Hermes\n"
            "  python scripts/nexusai_agent_worker.py --agent Hermes --ack --auto-reply --auto-reply-mode template\n"
            "  python scripts/nexusai_agent_worker.py --agent Hermes --ack --auto-reply --auto-reply-mode bridge-file --bridge-fallback none\n"
            "  python scripts/nexusai_agent_worker.py --agent Hermes --dry-run\n\n"
            "This script does not loop and does not execute commands."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default=os.getenv("NEXUSAI_URL", DEFAULT_BASE_URL), help="NexusAI base URL")
    parser.add_argument("--agent", required=True, help="Participant name to process, for example Hermes, Mira, or Nova")
    parser.add_argument("--ack", action="store_true", help="Acknowledge the message after marking it read")
    parser.add_argument("--auto-reply", nargs="?", const=DEFAULT_AUTO_REPLY, default="", metavar="TEXT", help="Create exactly one reply. Optional TEXT overrides ack-only/template generated text.")
    parser.add_argument("--auto-reply-mode", choices=AUTO_REPLY_MODES, default="ack-only", help="Reply behavior: ack-only, template, or bridge-file. agent-bridge is a deprecated alias for bridge-file.")
    parser.add_argument("--bridge-dir", default=str(DEFAULT_BRIDGE_DIR), help="Directory for bridge request/response JSON files")
    parser.add_argument("--bridge-fallback", choices=BRIDGE_FALLBACKS, default="none", help="Fallback when bridge-file response is missing/not ready")
    parser.add_argument("--dry-run", action="store_true", help="Print intended actions without POSTing read/ack/reply changes")
    return parser


def maybe_mark_read_ack(args: argparse.Namespace, message_id: int) -> None:
    if args.dry_run:
        print("DRY RUN: would mark message read")
    else:
        read_result = call("POST", f"/api/messages/{message_id}/read", {"participant": args.agent})
        print_json("Marked read:", read_result)
    if args.ack:
        if args.dry_run:
            print("DRY RUN: would acknowledge message")
        else:
            ack_result = call("POST", f"/api/messages/{message_id}/acknowledge", {"participant": args.agent})
            print_json("Acknowledged:", ack_result)


def post_reply(args: argparse.Namespace, message_id: int, reply_body: str, risk_level: str = DEFAULT_RISK) -> dict[str, Any] | None:
    reply_payload = {"from": args.agent, "body": reply_body, "risk_level": risk_level or DEFAULT_RISK}
    if args.dry_run:
        print_json("DRY RUN: would create one reply:", reply_payload)
        return None
    reply = call("POST", f"/api/messages/{message_id}/reply", reply_payload)
    print_json("Created one reply:", reply)
    if isinstance(reply, dict):
        if reply.get("requires_approval") or reply.get("status") == "pending_approval":
            print("Reply is pending Cameron approval before delivery.")
        else:
            print("Reply was not held for Cameron approval, likely because recipient is not an AI agent.")
    return reply if isinstance(reply, dict) else None


def handle_bridge_file(args: argparse.Namespace, message: dict[str, Any]) -> None:
    message_id = int(message["id"])
    request_path, response_path = bridge_paths(Path(args.bridge_dir), message_id, args.agent)
    print(f"Bridge request path: {request_path}")
    print(f"Bridge response path: {response_path}")
    response, status = load_bridge_response(response_path, message_id, args.agent)
    print(f"Bridge response status: {status}")
    if args.dry_run:
        print(f"DRY RUN: bridge request would be created: {request_path}")
        print(f"DRY RUN: response file exists: {'yes' if response_path.exists() else 'no'}")
        print(f"DRY RUN: reply would be posted: {'yes' if response is not None else 'no'}")
        return
    created = write_bridge_request(request_path, message, args.agent)
    print(f"Bridge request {'created' if created else 'already exists'}: {request_path}")
    if response is None:
        print(f"Bridge response not posted: {status}")
        if status != "missing" and not status.startswith("not ready"):
            print("Bridge response rejected/malformed; fix the response file and rerun.")
        if args.bridge_fallback == "none":
            print("No bridge fallback enabled; exiting without generic reply.")
            return
        fallback_body = build_auto_reply_body(message, args.bridge_fallback)
        print(f"Bridge fallback enabled: {args.bridge_fallback}")
        post_reply(args, message_id, fallback_body, DEFAULT_RISK)
        return
    if reply_already_exists(message, args.agent):
        print("Duplicate prevention: a reply from this agent already exists for this parent message; not posting again.")
        archive_bridge_files(request_path, response_path)
        return
    risk_level = response.get("risk_level") or DEFAULT_RISK
    if risk_level == UNKNOWN_RISK:
        print("Bridge response risk is UNKNOWN / NEEDS REVIEW; NexusAI must require approval before delivery.")
    post_reply(args, message_id, response["reply_body"], risk_level)
    archive_bridge_files(request_path, response_path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.auto_reply_mode == "agent-bridge":
        print("Auto-reply mode 'agent-bridge' is deprecated; using 'bridge-file'.")
        args.auto_reply_mode = "bridge-file"
    os.environ["NEXUSAI_URL"] = args.base_url.rstrip("/")
    print("NexusAI scheduled agent worker")
    print(f"Base URL: {os.environ['NEXUSAI_URL']}")
    print(f"Agent: {args.agent}")
    print(f"Dry run: {'yes' if args.dry_run else 'no'}")
    print(f"Auto-reply mode: {args.auto_reply_mode}")
    print(f"Bridge fallback: {args.bridge_fallback}")
    print("Safety: no command execution; approval does not equal execution.")
    if maybe_process_existing_bridge_response(args):
        print("Done. Processed one bridge response and exiting.")
        return 0
    encoded_agent = urllib.parse.quote(args.agent)
    inbox = call("GET", f"/api/agent-inbox/{encoded_agent}?limit=1")
    messages = inbox.get("messages", []) if isinstance(inbox, dict) else []
    if not messages:
        print("No messages")
        return 0
    message = messages[0]
    message_id = int(message["id"])
    print("Processing one delivered inbox message")
    print(f"Message ID: {message_id}")
    print(f"From: {message.get('from', '')}")
    print(f"Subject: {message.get('subject', '')}")
    if reply_already_exists(message, args.agent):
        print("Duplicate prevention: reply already exists for this parent message; not creating another reply.")
        maybe_mark_read_ack(args, message_id)
        print("Done. Processed at most one message and exiting.")
        return 0
    if not (args.dry_run and args.auto_reply and args.auto_reply_mode == "bridge-file"):
        maybe_mark_read_ack(args, message_id)
    if args.auto_reply:
        explicit_reply_text = "" if args.auto_reply == DEFAULT_AUTO_REPLY else args.auto_reply
        if args.auto_reply_mode == "bridge-file":
            handle_bridge_file(args, message)
        else:
            reply_body = build_auto_reply_body(message, args.auto_reply_mode, explicit_reply_text)
            post_reply(args, message_id, reply_body, DEFAULT_RISK)
    print("Done. Processed at most one message and exiting.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - scheduled logs need concise failures.
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
