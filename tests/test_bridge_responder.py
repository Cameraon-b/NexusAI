import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import nexusai_bridge_responder as responder  # noqa: E402


def write_request(bridge_dir: Path, message_id: int, agent: str = "Hermes", *, subject: str = "Bridge responder test", body: str = "Please help with this documentation note.") -> Path:
    path = bridge_dir / f"request-message-{message_id}-{agent}.json"
    path.write_text(
        json.dumps(
            {
                "message_id": message_id,
                "conversation_id": 7,
                "agent": agent,
                "from": "Mira",
                "to": agent,
                "subject": subject,
                "body": body,
                "risk_level": "DOCUMENTATION ONLY",
                "instructions": "Write one concise useful reply. Do not claim command execution.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_responder_finds_one_request_file(tmp_path):
    write_request(tmp_path, 30)
    write_request(tmp_path, 31, agent="Mira")

    requests = responder.find_pending_requests(tmp_path, "Hermes")

    assert [item.message_id for item in requests] == [30]


def test_template_responder_writes_matching_ready_response(tmp_path):
    write_request(tmp_path, 30, subject="README cleanup", body="Can you propose a short README wording update?")

    code = responder.main(["--agent", "Hermes", "--bridge-dir", str(tmp_path), "--mode", "template"])

    assert code == 0
    response_path = tmp_path / "response-message-30-Hermes.json"
    assert response_path.exists()
    data = json.loads(response_path.read_text(encoding="utf-8"))
    assert data["message_id"] == 30
    assert data["agent"] == "Hermes"
    assert data["ready"] is True
    assert data["risk_level"] == "DOCUMENTATION ONLY"
    assert data["created_by"] == "Hermes bridge responder"
    assert "README cleanup" in data["reply_body"]


def test_responder_does_not_overwrite_existing_response_by_default(tmp_path):
    write_request(tmp_path, 30)
    response_path = tmp_path / "response-message-30-Hermes.json"
    response_path.write_text('{"message_id": 30, "agent": "Hermes", "reply_body": "Existing", "ready": true}\n', encoding="utf-8")

    code = responder.main(["--agent", "Hermes", "--bridge-dir", str(tmp_path), "--mode", "template"])

    assert code == 0
    assert json.loads(response_path.read_text(encoding="utf-8"))["reply_body"] == "Existing"


def test_responder_overwrites_existing_response_when_requested(tmp_path):
    write_request(tmp_path, 30, subject="Overwrite test")
    response_path = tmp_path / "response-message-30-Hermes.json"
    response_path.write_text('{"message_id": 30, "agent": "Hermes", "reply_body": "Existing", "ready": true}\n', encoding="utf-8")

    code = responder.main(["--agent", "Hermes", "--bridge-dir", str(tmp_path), "--mode", "template", "--overwrite"])

    assert code == 0
    assert json.loads(response_path.read_text(encoding="utf-8"))["reply_body"] != "Existing"


def test_responder_exits_after_one_request(tmp_path):
    write_request(tmp_path, 30)
    write_request(tmp_path, 31)

    code = responder.main(["--agent", "Hermes", "--bridge-dir", str(tmp_path), "--mode", "template"])

    assert code == 0
    assert (tmp_path / "response-message-30-Hermes.json").exists()
    assert not (tmp_path / "response-message-31-Hermes.json").exists()


def test_infrastructure_request_gets_unknown_risk(tmp_path):
    write_request(
        tmp_path,
        30,
        subject="Docker deployment check",
        body="Should we run docker compose restart over SSH after the deploy?",
    )

    responder.main(["--agent", "Hermes", "--bridge-dir", str(tmp_path), "--mode", "template"])

    data = json.loads((tmp_path / "response-message-30-Hermes.json").read_text(encoding="utf-8"))
    assert data["risk_level"] == "UNKNOWN / NEEDS REVIEW"
    assert "proposed" in data["reply_body"].lower() or "review" in data["reply_body"].lower()
    assert "I restarted" not in data["reply_body"]


def test_manual_prompt_writes_prompt_file_without_response(tmp_path, capsys):
    write_request(tmp_path, 30, subject="Manual prompt test")

    code = responder.main(["--agent", "Hermes", "--bridge-dir", str(tmp_path), "--mode", "manual-prompt", "--write-prompt"])

    assert code == 0
    prompt_path = tmp_path / "prompt-message-30-Hermes.txt"
    assert prompt_path.exists()
    assert "Manual prompt test" in prompt_path.read_text(encoding="utf-8")
    assert not (tmp_path / "response-message-30-Hermes.json").exists()
    assert "Manual prompt test" in capsys.readouterr().out


def test_template_mode_uses_no_external_api(tmp_path, monkeypatch):
    write_request(tmp_path, 30)

    def blocked(*_args, **_kwargs):
        raise AssertionError("external process/network API should not be called")

    monkeypatch.setattr(responder, "request", blocked, raising=False)
    monkeypatch.setattr(responder, "subprocess", blocked, raising=False)

    code = responder.main(["--agent", "Hermes", "--bridge-dir", str(tmp_path), "--mode", "template"])

    assert code == 0
    assert (tmp_path / "response-message-30-Hermes.json").exists()
