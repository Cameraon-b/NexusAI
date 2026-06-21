$Project = "C:\FilesForNora\NexusAI"
$LogDir = "$Project\logs"
$Log = "$LogDir\hermes-poller.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

"--- Hermes poller start: $(Get-Date) ---" | Out-File -FilePath $Log -Append
"User: $env:USERNAME" | Out-File -FilePath $Log -Append
"Project: $Project" | Out-File -FilePath $Log -Append

Set-Location $Project

py "$Project\scripts\nexusai_agent_worker.py" `
  --base-url "http://127.0.0.1:5055" `
  --agent "Hermes" `
  --ack `
  --auto-reply `
  --auto-reply-mode "template" 2>&1 | Out-File -FilePath $Log -Append

"Exit code: $LASTEXITCODE" | Out-File -FilePath $Log -Append
"--- Hermes poller end: $(Get-Date) ---" | Out-File -FilePath $Log -Append
"" | Out-File -FilePath $Log -Append