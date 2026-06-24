import os
import sys
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import nexusai_agent_worker as worker  # noqa: E402

from app.main import app


@contextmanager
def client(tmp_path: Path):
    old_db = os.environ.get('NEXUSAI_DB_PATH')
    os.environ['NEXUSAI_DB_PATH'] = str(tmp_path / 'test-nexusai.db')
    try:
        with TestClient(app) as c:
            yield c
    finally:
        if old_db is None:
            os.environ.pop('NEXUSAI_DB_PATH', None)
        else:
            os.environ['NEXUSAI_DB_PATH'] = old_db


def test_version_endpoint_returns_build_info_without_commit_file(tmp_path, monkeypatch):
    from app import main as app_main

    missing_commit = tmp_path / 'missing-commit-file'
    monkeypatch.setattr(app_main, 'COMMIT_FILE', missing_commit)

    with client(tmp_path) as c:
        res = c.get('/api/version')
        assert res.status_code == 200
        data = res.json()
        assert data['app'] == 'NexusAI'
        assert data['version']
        assert data['commit'] == 'unknown'
        assert data['environment'] == 'AETHER'
        assert data['host'] == 'Nora'


def test_version_endpoint_prefers_runtime_environment_commit(tmp_path, monkeypatch):
    from app import main as app_main

    commit_file = tmp_path / '.nexusai_commit'
    commit_file.write_text('file9999\n', encoding='utf-8')
    monkeypatch.setattr(app_main, 'COMMIT_FILE', commit_file)
    monkeypatch.setenv('NEXUSAI_COMMIT', 'env1234')
    monkeypatch.setenv('NEXUSAI_ENVIRONMENT', 'AETHER')
    monkeypatch.setenv('NEXUSAI_HOST', 'Nora')

    with client(tmp_path) as c:
        data = c.get('/api/version').json()
        assert data == {
            'app': 'NexusAI',
            'version': '0.05',
            'commit': 'env1234',
            'environment': 'AETHER',
            'host': 'Nora',
        }


def test_health_endpoint_includes_version_build_info(tmp_path, monkeypatch):
    from app import main as app_main

    commit_file = tmp_path / '.nexusai_commit'
    commit_file.write_text('abc1234\n', encoding='utf-8')
    monkeypatch.setattr(app_main, 'COMMIT_FILE', commit_file)

    with client(tmp_path) as c:
        data = c.get('/api/health').json()
        assert data['app'] == 'NexusAI'
        assert data['version']
        assert data['commit'] == 'abc1234'
        assert data['environment'] == 'AETHER'
        assert data['host'] == 'Nora'
        assert data['command_execution'] == 'disabled'


def test_frontend_static_contains_visible_version_mount_and_fetch(tmp_path):
    with client(tmp_path) as c:
        html = c.get('/').text
        js = c.get('/static/app.js').text
        assert 'id="version-status"' in html
        assert 'Loading build info' in html
        assert "api('/version')" in js
        assert 'renderVersion' in js
        assert 'unknown' in js


def test_participants_and_reference_data_seeded(tmp_path):
    with client(tmp_path) as c:
        res = c.get('/api/participants')
        assert res.status_code == 200
        display_names = [a['display_name'] for a in res.json()]
        for name in ['Cameron', 'Nova', 'Mira', 'Hermes', 'OpenClaw', 'Nora', 'BookStack', 'Uptime Kuma', 'System']:
            assert name in display_names

        risks = [r['name'] for r in c.get('/api/risk-levels').json()]
        assert 'AI-TO-AI PENDING' not in risks
        assert 'BUILD / UI' in risks


def test_create_human_message_and_logs_action(tmp_path):
    with client(tmp_path) as c:
        payload = {
            'from': 'Mira',
            'to': 'Cameron',
            'subject': 'Review Docker Service Recovery page',
            'body': 'Please review path consistency against the current Backup Strategy page.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
        }
        res = c.post('/api/messages', json=payload)
        assert res.status_code == 201
        msg = res.json()
        assert msg['id'] > 0
        assert msg['from'] == 'Mira'
        assert msg['to'] == 'Cameron'
        assert msg['risk_level'] == 'DOCUMENTATION ONLY'
        assert msg['status'] == 'delivered'
        assert msg['requires_approval'] is False

        logs = c.get('/api/logs').json()
        assert any(l['action_type'] == 'create' and l['target_type'] == 'message' and l['target_id'] == msg['id'] for l in logs)


def test_ai_to_ai_message_requires_approval_and_approval_delivers(tmp_path):
    with client(tmp_path) as c:
        res = c.post('/api/messages', json={
            'from': 'Mira',
            'to': 'Hermes',
            'subject': 'README update request',
            'body': 'Please review the README wording.',
            'risk_level': 'AI-TO-AI PENDING',
            'status': 'delivered',
        })
        assert res.status_code == 201
        msg = res.json()
        assert msg['status'] == 'pending_approval'
        assert msg['requires_approval'] is True
        assert msg['delivery_status'] == 'pending_approval'

        approvals = c.get('/api/approvals').json()
        delivery_approval = next(a for a in approvals if a['target_type'] == 'message' and a['target_id'] == msg['id'])
        approved = c.patch(f"/api/approvals/{delivery_approval['id']}", json={'status': 'approved', 'approved_by': 'Cameron'})
        assert approved.status_code == 200
        delivered = c.get(f"/api/messages/{msg['id']}").json()
        assert delivered['status'] == 'delivered'
        assert delivered['requires_approval'] is True
        assert delivered['risk_level'] == 'DOCUMENTATION ONLY'
        assert delivered['approved_by'] == 'Cameron'
        assert delivered['approved_at']


def test_create_and_patch_task(tmp_path):
    with client(tmp_path) as c:
        res = c.post('/api/tasks', json={
            'title': 'Draft service registry',
            'description': 'Create a first-pass list of AETHER services.',
            'created_by': 'Hermes',
            'assigned_to': 'Mira',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'open',
        })
        assert res.status_code == 201
        task_id = res.json()['id']

        patched = c.patch(f'/api/tasks/{task_id}', json={'status': 'completed', 'completion_notes': 'Draft complete.'})
        assert patched.status_code == 200
        assert patched.json()['status'] == 'completed'
        assert patched.json()['completion_notes'] == 'Draft complete.'
        assert patched.json()['completed_at']


def test_approval_records_but_does_not_execute(tmp_path):
    with client(tmp_path) as c:
        res = c.post('/api/approvals', json={
            'requested_by': 'Hermes',
            'requested_for': 'Cameron',
            'action_summary': 'Restart BookStack Docker Compose service',
            'proposed_command': 'cd /home/noratheredeemer/docker/bookstack && docker compose restart',
            'risk_level': 'STATE-CHANGING / APPROVAL REQUIRED',
            'reason': 'BookStack is unreachable after restore validation.',
            'status': 'pending',
        })
        assert res.status_code == 201
        approval_id = res.json()['id']

        approved = c.patch(f'/api/approvals/{approval_id}', json={'status': 'approved', 'approved_by': 'Cameron'})
        assert approved.status_code == 200
        body = approved.json()
        assert body['status'] == 'approved'
        assert body['approved_by'] == 'Cameron'
        assert body['proposed_command'].startswith('cd /home/noratheredeemer')

        logs = c.get('/api/logs').json()
        assert any('no command executed' in l['summary'].lower() for l in logs)


def test_review_notice_and_service_endpoints(tmp_path):
    with client(tmp_path) as c:
        review = c.post('/api/reviews', json={
            'title': 'Review NexusAI schema',
            'body': 'Check participant and risk-level normalization.',
            'requested_by': 'Hermes',
            'reviewer': 'Nova',
            'target_type': 'database',
            'target_ref': 'docs/NexusAIDBV1.0.png',
            'risk_level': 'REVIEW',
            'status': 'open',
        })
        assert review.status_code == 201
        assert review.json()['reviewer'] == 'Nova'

        notice = c.post('/api/notices', json={
            'service': 'BookStack',
            'source': 'Uptime Kuma',
            'severity': 'warning',
            'title': 'BookStack response time elevated',
            'body': 'Monitor warning only. No remediation was executed.',
            'risk_level': 'WARNING',
            'status': 'active',
        })
        assert notice.status_code == 201
        assert notice.json()['service'] == 'BookStack'

        services = c.get('/api/services')
        assert services.status_code == 200
        assert any(s['name'] == 'NexusAI' for s in services.json())


def test_invalid_risk_label_rejected(tmp_path):
    with client(tmp_path) as c:
        res = c.post('/api/tasks', json={
            'title': 'Bad task',
            'description': 'This should fail.',
            'created_by': 'Hermes',
            'assigned_to': 'Mira',
            'risk_level': 'LOW',
            'status': 'open',
        })
        assert res.status_code == 422


def test_dashboard_matches_design_material_sections(tmp_path):
    with client(tmp_path) as c:
        dash = c.get('/api/dashboard')
        assert dash.status_code == 200
        body = dash.json()
        for key in ['open_messages', 'open_tasks', 'pending_approvals', 'open_reviews', 'active_notices', 'recent_logs']:
            assert key in body



def test_agent_inbox_read_ack_reply_and_logs(tmp_path):
    with client(tmp_path) as c:
        msg = c.post('/api/messages', json={
            'from': 'Cameron',
            'to': 'Hermes',
            'subject': 'Agent inbox smoke test',
            'body': 'Please acknowledge this delivered message.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
        }).json()

        inbox = c.get('/api/agent-inbox/Hermes?limit=1')
        assert inbox.status_code == 200
        assert inbox.json()['messages'][0]['id'] == msg['id']

        read = c.post(f"/api/messages/{msg['id']}/read", json={'participant': 'Hermes'})
        assert read.status_code == 200
        assert read.json()['delivery_status'] == 'read'

        ack = c.post(f"/api/messages/{msg['id']}/acknowledge", json={'participant': 'Hermes'})
        assert ack.status_code == 200
        assert ack.json()['delivery_status'] == 'acknowledged'

        reply = c.post(f"/api/messages/{msg['id']}/reply", json={
            'from': 'Hermes',
            'body': 'Acknowledged. This is a documentation-only reply.',
            'risk_level': 'DOCUMENTATION ONLY',
        })
        assert reply.status_code == 201
        body = reply.json()
        assert body['parent_message_id'] == msg['id']
        assert body['conversation_id'] == msg['conversation_id']
        assert body['status'] == 'delivered'  # human recipient, no AI-to-AI gate

        logs = c.get('/api/logs').json()
        actions = [l['action_type'] for l in logs]
        assert 'check_inbox' in actions
        assert 'read' in actions
        assert 'acknowledge' in actions
        assert 'create_reply' in actions


def approve_message_delivery(c, message_id: int):
    approval = next(a for a in c.get('/api/approvals').json() if a['target_id'] == message_id and a['target_type'] == 'message')
    approved = c.patch(f"/api/approvals/{approval['id']}", json={'status': 'approved', 'approved_by': 'Cameron'})
    assert approved.status_code == 200
    return approved.json()


def test_reply_endpoint_routes_mira_to_hermes_parent_back_to_mira(tmp_path):
    with client(tmp_path) as c:
        parent = c.post('/api/messages', json={
            'from': 'Mira',
            'to': 'Hermes',
            'subject': 'Routing test Mira parent',
            'body': 'Hermes should reply to Mira.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
        }).json()
        approve_message_delivery(c, parent['id'])

        reply = c.post(f"/api/messages/{parent['id']}/reply", json={
            'from': 'Hermes',
            'body': 'Reply back to Mira.',
            'risk_level': 'DOCUMENTATION ONLY',
        })

        assert reply.status_code == 201
        body = reply.json()
        assert body['from'] == 'Hermes'
        assert body['to'] == 'Mira'
        assert body['conversation_id'] == parent['conversation_id']
        assert body['parent_message_id'] == parent['id']
        assert body['status'] == 'pending_approval'
        assert body['delivery_status'] == 'pending_approval'
        assert body['requires_approval'] is True


def test_reply_endpoint_routes_hermes_to_mira_parent_back_to_hermes(tmp_path):
    with client(tmp_path) as c:
        parent = c.post('/api/messages', json={
            'from': 'Hermes',
            'to': 'Mira',
            'subject': 'Routing test Hermes parent',
            'body': 'Mira should reply to Hermes.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
        }).json()
        approve_message_delivery(c, parent['id'])

        reply = c.post(f"/api/messages/{parent['id']}/reply", json={
            'from': 'Mira',
            'body': 'Reply back to Hermes.',
            'risk_level': 'DOCUMENTATION ONLY',
        })

        assert reply.status_code == 201
        body = reply.json()
        assert body['from'] == 'Mira'
        assert body['to'] == 'Hermes'
        assert body['conversation_id'] == parent['conversation_id']
        assert body['parent_message_id'] == parent['id']
        assert body['status'] == 'pending_approval'
        assert body['delivery_status'] == 'pending_approval'
        assert body['requires_approval'] is True


def test_reply_endpoint_rejects_sender_that_is_not_parent_recipient(tmp_path):
    with client(tmp_path) as c:
        parent = c.post('/api/messages', json={
            'from': 'Hermes',
            'to': 'Mira',
            'subject': 'Bad self reply test',
            'body': 'Hermes should not reply as Hermes to its own parent message.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
        }).json()
        approve_message_delivery(c, parent['id'])

        reply = c.post(f"/api/messages/{parent['id']}/reply", json={
            'from': 'Hermes',
            'body': 'This would route Hermes to Hermes and must be rejected.',
            'risk_level': 'DOCUMENTATION ONLY',
        })

        assert reply.status_code == 409
        assert 'parent message recipient' in reply.json()['detail']


def test_agent_inbox_hides_pending_ai_to_ai_until_cameron_approval(tmp_path):
    with client(tmp_path) as c:
        res = c.post('/api/messages', json={
            'from': 'Hermes',
            'to': 'Mira',
            'subject': 'Pending approval inbox test',
            'body': 'This should wait for Cameron approval.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
        })
        assert res.status_code == 201
        msg = res.json()
        assert msg['risk_level'] == 'DOCUMENTATION ONLY'
        assert msg['requested_risk_level'] == 'DOCUMENTATION ONLY'
        assert msg['status'] == 'pending_approval'
        assert msg['delivery_status'] == 'pending_approval'
        assert c.get('/api/agent-inbox/Mira?limit=1').json()['messages'] == []

        approval = next(a for a in c.get('/api/approvals').json() if a['target_id'] == msg['id'] and a['target_type'] == 'message')
        approved = c.patch(f"/api/approvals/{approval['id']}", json={'status': 'approved', 'approved_by': 'Cameron'})
        assert approved.status_code == 200
        inbox = c.get('/api/agent-inbox/Mira?limit=1').json()
        assert inbox['messages'][0]['id'] == msg['id']


def test_cameron_rejection_marks_message_rejected(tmp_path):
    with client(tmp_path) as c:
        msg = c.post('/api/messages', json={
            'from': 'Hermes',
            'to': 'Mira',
            'subject': 'Reject delivery test',
            'body': 'This should be rejected.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
        }).json()
        approval = next(a for a in c.get('/api/approvals').json() if a['target_id'] == msg['id'] and a['target_type'] == 'message')
        rejected = c.patch(f"/api/approvals/{approval['id']}", json={'status': 'rejected', 'approved_by': 'Cameron', 'decision_notes': 'Not needed.'})
        assert rejected.status_code == 200
        fetched = c.get(f"/api/messages/{msg['id']}").json()
        assert fetched['status'] == 'rejected'
        assert fetched['delivery_status'] == 'rejected'
        assert c.get('/api/agent-inbox/Mira?limit=1').json()['messages'] == []


def test_conversation_max_turns_pauses_replies(tmp_path):
    with client(tmp_path) as c:
        conv = c.post('/api/conversations', json={'title': 'Short conversation', 'created_by': 'Cameron', 'max_turns': 1}).json()
        msg = c.post('/api/messages', json={
            'from': 'Cameron',
            'to': 'Hermes',
            'subject': 'One turn only',
            'body': 'This consumes the only turn.',
            'risk_level': 'DOCUMENTATION ONLY',
            'status': 'delivered',
            'conversation_id': conv['id'],
        }).json()
        blocked = c.post(f"/api/messages/{msg['id']}/reply", json={'from': 'Hermes', 'body': 'Should be blocked.'})
        assert blocked.status_code == 409
        assert c.get(f"/api/conversations/{conv['id']}").json()['status'] == 'paused'


def test_bridge_file_response_validation_and_archival(tmp_path):
    message = {
        'id': 42,
        'conversation_id': 7,
        'from': 'Mira',
        'to': 'Hermes',
        'subject': 'NexusAI deployment checklist',
        'body': 'Please review what should be validated before agent bridge testing.',
        'risk_level': 'DOCUMENTATION ONLY',
    }
    request_path, response_path = worker.bridge_paths(tmp_path, 42, 'Hermes')
    created = worker.write_bridge_request(request_path, message, 'Hermes')
    assert created is True
    request_body = request_path.read_text(encoding='utf-8')
    assert 'Do not claim to execute commands' in request_body
    assert 'NexusAI deployment checklist' in request_body

    response_path.write_text('{not json', encoding='utf-8')
    response, status = worker.load_bridge_response(response_path, 42, 'Hermes')
    assert response is None
    assert status.startswith('malformed JSON')

    response_path.write_text('{"message_id": 42, "agent": "Hermes", "ready": false}', encoding='utf-8')
    response, status = worker.load_bridge_response(response_path, 42, 'Hermes')
    assert response is None
    assert status == 'not ready'

    response_path.write_text(
        '{"message_id": 42, "agent": "Hermes", "reply_body": "Bridge response ready.", "risk_level": "DOCUMENTATION ONLY", "ready": true}',
        encoding='utf-8',
    )
    response, status = worker.load_bridge_response(response_path, 42, 'Hermes')
    assert status == 'ready'
    assert response['reply_body'] == 'Bridge response ready.'
    worker.archive_bridge_files(request_path, response_path)
    assert not request_path.exists()
    assert not response_path.exists()
    assert list((tmp_path / 'archive').glob('*processed*.json'))


def test_ui_static_exposes_design_views_and_no_run_buttons(tmp_path):
    with client(tmp_path) as c:
        js = c.get('/static/app.js')
        assert js.status_code == 200
        body = js.text
        assert 'openMessage' in body
        assert 'openTask' in body
        assert 'openApproval' in body
        assert 'openReview' in body
        assert 'openNotice' in body
        assert 'Full body' in body
        assert 'Full description' in body
        assert 'Proposed command / action text' in body
        assert 'Safety warning: Approval records permission only' in body
        assert 'Run command' not in body
        assert 'Run service' not in body
        assert 'execute this command' in body

        html = c.get('/')
        assert html.status_code == 200
        assert 'Reviews' in html.text
        assert 'Notices' in html.text
        assert 'Services' in html.text
