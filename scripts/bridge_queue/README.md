# Bridge Queue

Runtime request/response JSON files for `nexusai_agent_worker.py --auto-reply-mode bridge-file` are written here and ignored by git.

- request files: `request-message-<message_id>-<agent>.json`
- response files: `response-message-<message_id>-<agent>.json`
- processed files move to `archive/`

NexusAI does not execute commands from these files.
