import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import nexusai_agent_worker as worker  # noqa: E402


def test_auto_reply_mode_defaults_to_ack_only():
    args = worker.build_parser().parse_args(["--agent", "Hermes"])

    assert args.auto_reply_mode == "ack-only"


def test_auto_reply_mode_accepts_template_and_rejects_unknown():
    parser = worker.build_parser()

    args = parser.parse_args(["--agent", "Hermes", "--auto-reply", "--auto-reply-mode", "template"])

    assert args.auto_reply_mode == "template"
    with pytest.raises(SystemExit):
        parser.parse_args(["--agent", "Hermes", "--auto-reply-mode", "execute"])


def test_ack_only_reply_matches_existing_safe_generic_ack():
    message = {
        "subject": "Deployment checklist",
        "body": "Please review the deployment checklist only.",
    }

    body = worker.build_auto_reply_body(message, "ack-only")

    assert body == worker.DEFAULT_AUTO_REPLY


def test_template_reply_is_contextual_and_omits_irrelevant_safety_statement():
    message = {
        "subject": "Task board setup",
        "body": "Can you help shape how Hermes and Mira should exchange task updates in NexusAI?",
    }

    body = worker.build_auto_reply_body(message, "template")

    assert "Task board setup" in body
    assert "task" in body.lower()
    assert "NexusAI remains a coordination" not in body
    assert "Next" in body or "Question" in body or "Checklist" in body
    sentence_count = sum(body.count(p) for p in ".?!")
    assert 2 <= sentence_count <= 5


def test_template_reply_adds_safety_line_only_for_system_change_topics():
    message = {
        "subject": "BookStack deployment approval",
        "body": "Should we run docker compose restart after Cameron approves the deployment?",
    }

    body = worker.build_auto_reply_body(message, "template")

    assert "BookStack deployment approval" in body
    assert "approval" in body.lower()
    assert "execution" in body.lower() or "executed" in body.lower()


def test_agent_bridge_mode_aliases_bridge_file_and_does_not_generate_immediate_body():
    parser = worker.build_parser()
    args = parser.parse_args(["--agent", "Hermes", "--auto-reply", "--auto-reply-mode", "bridge-file", "--bridge-fallback", "none"])
    assert args.auto_reply_mode == "bridge-file"
    message = {"subject": "Future bridge", "body": "Please hand this to the real runtime later."}
    with pytest.raises(ValueError):
        worker.build_auto_reply_body(message, "bridge-file")
