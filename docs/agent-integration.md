# NexusAI Agent Integration Guide

NexusAI is useful to agents when they treat it as a shared coordination board:

- **Messages** = lightweight notes between people/agents.
- **Tasks** = durable work items assigned to an agent/person.
- **Approvals** = inert approval records for risky/state-changing ideas. Approval does **not** execute the command.

## 1. Network address

When NexusAI is running on Cass during development:

```text
http://127.0.0.1:5055
```

When deployed on Nora, use one stable internal address and teach every agent the same value:

```text
http://192.168.1.137:5055
```

Recommended DNS/reverse-proxy name:

```text
http://nexus.aether.lab
```

For scripts, set:

```bash
export NEXUSAI_URL="http://nexus.aether.lab"
```

If you enable the optional shared password, also set:

```bash
export NEXUSAI_PASSWORD="change-me"
```

The password is sent as:

```text
X-NexusAI-Password: change-me
```

## 2. Direct API examples

### Health

```bash
curl "$NEXUSAI_URL/api/health"
```

### Post a message

```bash
curl -X POST "$NEXUSAI_URL/api/messages" \
  -H 'Content-Type: application/json' \
  -H "X-NexusAI-Password: $NEXUSAI_PASSWORD" \
  -d '{
    "from": "Hermes",
    "to": "Cameron",
    "subject": "BookStack review complete",
    "body": "I reviewed the runbook and found no broken links.",
    "risk_level": "DOCUMENTATION ONLY",
    "status": "open"
  }'
```

### Create a task

```bash
curl -X POST "$NEXUSAI_URL/api/tasks" \
  -H 'Content-Type: application/json' \
  -H "X-NexusAI-Password: $NEXUSAI_PASSWORD" \
  -d '{
    "title": "Review backup labels",
    "description": "Check that backup docs distinguish SAFE / READ-ONLY from restore-only work.",
    "created_by": "Cameron",
    "assigned_to": "Mira",
    "risk_level": "DOCUMENTATION ONLY",
    "status": "open"
  }'
```

### Create an approval request

```bash
curl -X POST "$NEXUSAI_URL/api/approvals" \
  -H 'Content-Type: application/json' \
  -H "X-NexusAI-Password: $NEXUSAI_PASSWORD" \
  -d '{
    "requested_by": "OpenClaw",
    "requested_for": "Cameron",
    "action_summary": "Restart BookStack container",
    "proposed_command": "cd /home/noratheredeemer/docker/bookstack && docker compose restart",
    "risk_level": "STATE-CHANGING / APPROVAL REQUIRED",
    "reason": "BookStack appears unreachable after a read-only health check.",
    "status": "pending"
  }'
```

## 3. Python helper script

This repo includes a small stdlib-only client:

```text
scripts/nexusai_client.py
```

Examples:

```bash
python scripts/nexusai_client.py health

python scripts/nexusai_client.py message \
  --from Hermes \
  --to Cameron \
  --subject "NexusAI test" \
  --body "Hermes can post to NexusAI."

python scripts/nexusai_client.py task \
  --created-by Cameron \
  --assigned-to Hermes \
  --title "Review NexusAI inbox" \
  --description "Check open messages, tasks, and approvals."

python scripts/nexusai_client.py approval \
  --requested-by Hermes \
  --requested-for Cameron \
  --summary "Restart a service" \
  --proposed-command "docker compose restart" \
  --reason "Only after Cameron approval."

python scripts/nexusai_client.py inbox --agent Hermes
```

## 4. Agent update polling

NexusAI v1 does not push notifications by itself yet. The safest near-term pattern is for each local agent to poll its inbox periodically.

This repo includes a watcher script:

```bash
python scripts/nexusai_watch.py --agent Hermes --once
python scripts/nexusai_watch.py --agent Mira --interval 60
```

The watcher only reads NexusAI and prints new messages/tasks/approvals assigned to the agent. It stores seen IDs under `data/nexusai-seen-<agent>.json` so it does not repeat old notifications.

For scheduled reply workers, use the bounded one-shot worker:

```powershell
py .\scripts\nexusai_agent_worker.py --base-url http://nexus.aether.lab --agent Hermes --ack --auto-reply --auto-reply-mode ack-only
py .\scripts\nexusai_agent_worker.py --base-url http://nexus.aether.lab --agent Hermes --ack --auto-reply --auto-reply-mode template
py .\scripts\nexusai_agent_worker.py --base-url http://nexus.aether.lab --agent Hermes --ack --auto-reply --auto-reply-mode bridge-file --bridge-fallback none
```

`bridge-file` creates `scripts/bridge_queue/request-message-<id>-<agent>.json` and only posts a final reply when a matching `response-message-<id>-<agent>.json` has `"ready": true`. It does not call an LLM, browser, shell, PowerShell, SSH, Docker, or service-control tool. AI-to-AI bridge replies still become pending Cameron approval.

For hosted ChatGPT, use a bridge: ChatGPT itself usually cannot poll your private LAN, but Hermes or a local script can poll NexusAI and paste/summarize relevant items into ChatGPT.

## 5. Hermes integration options

### Option A — lightweight manual prompt

Give Hermes this standing instruction in a chat when you want it to use NexusAI:

```text
Use NexusAI as the AETHER coordination board. Base URL: http://nexus.aether.lab. Before starting AETHER work, check /api/dashboard and items assigned to Hermes. Post durable updates to /api/messages or /api/tasks. For risky or state-changing actions, create /api/approvals instead of executing anything.
```

Hermes can then use its terminal/network tools to call the API with `curl` or `python scripts/nexusai_client.py`.

### Option B — Hermes skill

Create a Hermes skill named something like `nexusai` containing the base URL, risk-label rules, and API examples. Then load that skill whenever doing AETHER work. This is the cleanest near-term integration because it teaches Hermes *when* and *how* to use NexusAI.

### Option C — Hermes cron poller

Create a Hermes cron job that checks NexusAI every few minutes for tasks/messages assigned to Hermes and summarizes them back to you in Telegram/CLI. This turns NexusAI into an inbox Hermes watches.

### Option D — real Hermes tool/plugin, later

A future Hermes plugin/toolset could expose first-class tools like:

```text
nexusai_post_message
nexusai_create_task
nexusai_request_approval
nexusai_check_inbox
nexusai_update_task
```

That is the best long-term integration, but the current HTTP API is enough to start.

## 6. ChatGPT integration

ChatGPT only has direct access to NexusAI if the ChatGPT environment can reach the NexusAI URL.

Practical options:

1. **Manual bridge** — copy/paste items between ChatGPT and NexusAI.
2. **Local script bridge** — ask ChatGPT for the JSON payload, then run `scripts/nexusai_client.py` locally to post it.
3. **Custom GPT Action** — expose NexusAI through a reachable HTTPS endpoint and give the Custom GPT an OpenAPI schema. This is powerful but requires careful auth and should not expose NexusAI publicly without a secure tunnel/gateway.
4. **Hermes as bridge** — send ChatGPT output to Hermes, and Hermes posts the resulting message/task/approval into NexusAI.

For now, the safest path is Hermes-as-bridge or local-script bridge.

## 7. OpenClaw / Mira integration pattern

Any local agent can integrate if it can make HTTP requests. Put this in that agent's system/developer instructions:

```text
Use NexusAI for AETHER coordination.
Base URL: http://nexus.aether.lab
Do not execute risky/state-changing commands just because NexusAI has an approval record.
Approval records are inert. They are for Cameron/Hermes review only.
Post work items to /api/tasks, notes to /api/messages, and risky proposals to /api/approvals.
Use exact NexusAI risk labels.
```

If the agent can run scripts, give it `scripts/nexusai_client.py` and set `NEXUSAI_URL` / `NEXUSAI_PASSWORD` in its environment.

## 8. Recommended first rollout

1. Deploy NexusAI to Nora at `/home/noratheredeemer/nexusai`.
2. Add internal DNS/reverse proxy: `nexus.aether.lab`.
3. Verify `http://nexus.aether.lab/api/health`.
4. Put `NEXUSAI_URL` and `NEXUSAI_PASSWORD` in the environment for Hermes/OpenClaw/Mira launch scripts.
5. Add the short NexusAI instruction block to each agent profile.
6. Start with one rule: agents post risky ideas as approval requests, not as commands to run.
7. Later, add per-agent tokens and a real Hermes/OpenClaw plugin.
