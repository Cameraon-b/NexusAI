const API = '/api';

const riskLevels = [
  'SAFE / READ-ONLY',
  'DOCUMENTATION ONLY',
  'BACKUP WRITE OPERATION',
  'STATE-CHANGING / APPROVAL REQUIRED',
  'RESTORE-ONLY / HIGH RISK',
  'DESTRUCTIVE / EXPLICIT APPROVAL REQUIRED',
  'WARNING',
  'REVIEW',
  'BUILD / UI',
  'UNKNOWN / NEEDS REVIEW'
];
const participants = ['Cameron', 'Nova', 'Mira', 'Hermes', 'OpenClaw', 'Nora', 'BookStack', 'Uptime Kuma', 'System'];
const messageStatuses = ['draft','pending_approval','delivered','acknowledged','completed','archived','rejected'];
const taskStatuses = ['open','in_progress','blocked','completed','archived','cancelled'];
const approvalStatuses = ['pending','approved','rejected','archived','cancelled'];
const reviewStatuses = ['open','in_progress','completed','archived','cancelled'];
const noticeStatuses = ['active','acknowledged','resolved','archived'];

async function api(path, options = {}) {
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  const res = await fetch(API + path, {...options, headers});
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}
function esc(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function titleize(value) { return String(value ?? '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()); }
function riskClass(risk, item = {}) {
  const text = String(risk || '').toUpperCase();
  if (item.status === 'pending_approval' || item.delivery_status === 'pending_approval') return 'pending-ai';
  if (text.includes('SAFE')) return 'safe';
  if (text.includes('DOCUMENTATION')) return 'doc';
  if (text.includes('BACKUP')) return 'backup';
  if (text.includes('STATE-CHANGING')) return 'state';
  if (text.includes('RESTORE')) return 'restore';
  if (text.includes('DESTRUCTIVE')) return 'destructive';
  if (text.includes('UNKNOWN')) return 'unknown';
  return '';
}
function riskBadge(risk, item = {}) { return `<span class="risk ${riskClass(risk, item)}">${esc(risk || 'UNKNOWN / NEEDS REVIEW')}</span>`; }
function statusPill(status) { return `<span class="status">${esc(titleize(status || 'unknown'))}</span>`; }
function select(name, values, selected) { return `<select name="${esc(name)}">${values.map(v => `<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(v)}</option>`).join('')}</select>`; }
function truncate(value, max = 115) { const text = String(value ?? ''); return text.length > max ? `${text.slice(0, max - 1)}…` : text; }
function page(title, subtitle, body) { document.querySelector('#app').innerHTML = `<section class="panel"><div class="page-title"><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${body}</section>`; }
function formData(event) { const data = Object.fromEntries(new FormData(event.target).entries()); Object.keys(data).forEach(k => data[k] === '' && delete data[k]); return data; }
function actionButton(label, fn) { return `<button type="button" onclick="${fn}">${esc(label)}</button>`; }
function recordList(items, render) { return items.length ? `<div class="record-list">${items.map(render).join('')}</div>` : '<p class="empty-state">No records yet.</p>'; }
function card(title, value, link) { return `<a class="metric" href="${link}"><strong>${esc(title)}</strong><span>${esc(value)}</span></a>`; }
function section(title, body, wide = false) { return `<section class="section-card ${wide?'wide':''}"><h2>${esc(title)}</h2><div class="section-body">${body}</div></section>`; }
function table(items, columns) {
  if (!items.length) return '<p class="empty-state">No records yet.</p>';
  return `<div class="table-wrap"><table><thead><tr>${columns.map(c => `<th>${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${items.map(item => `<tr>${columns.map(c => `<td>${c.render ? c.render(item) : esc(item[c.key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

async function dashboard() {
  const [data, conversations] = await Promise.all([api('/dashboard'), api('/conversations')]);
  const pendingAi = data.pending_approvals.filter(a => a.action_type === 'ai_to_ai_delivery');
  const agentLogs = latestAgentLogs(data.recent_logs);
  page('AETHER Operations Console', 'Attention Required, Agent Activity, approvals, conversations, notices, and audit history.', `
    <div class="safety-banner">Approval does not equal execution. NexusAI coordinates messages, approvals, and audit history only.</div>
    <div class="metrics">
      ${card('Pending Approvals', data.pending_approvals.length, '/approvals')}
      ${card('AI-to-AI Waiting', pendingAi.length, '/approvals')}
      ${card('Open Tasks', data.open_tasks.length, '/tasks')}
      ${card('Active Notices', data.active_notices.length, '/notices')}
    </div>
    <div class="dashboard-grid">
      ${section('Attention Required', recordList([...pendingAi, ...data.open_tasks.filter(t => t.status === 'blocked')], item => item.action_type ? approvalRow(item) : taskRow(item)))}
      ${section('Agent Activity', agentActivity(agentLogs))}
      ${section('Approval Queue', recordList(data.pending_approvals, approvalRow))}
      ${section('Conversation Threads', recordList(conversations.slice(0, 8), conversationRow))}
      ${section('Recent Messages', recordList(data.open_messages, messageRow))}
      ${section('System Notices', recordList(data.active_notices, noticeRow))}
      ${section('Deployment Status', deploymentStatus(), true)}
      ${section('Recent Action Log', logLines(data.recent_logs), true)}
    </div>`);
}
function latestAgentLogs(logs) {
  const agents = ['Hermes', 'Mira', 'Nova'];
  return agents.map(agent => ({agent, last: logs.find(l => l.actor === agent) || null}));
}
function agentActivity(items) { return `<div class="record-list">${items.map(i => `<div class="record-row"><div class="row-title">${esc(i.agent)}</div><div class="row-meta">${i.last ? `${esc(i.last.timestamp)} · ${esc(i.last.action_type)} · ${esc(truncate(i.last.summary, 90))}` : 'No recent activity in latest log window.'}</div><div class="row-meta">Mode: scheduled poller / bridge-file capable</div></div>`).join('')}</div>`; }
function deploymentStatus() { return `<div class="record-list"><div class="record-row"><div class="row-title">Nora deployment</div><div class="row-meta">Internal URL: http://nexus.aether.lab · Health: /api/health · Deploy path: /home/noratheredeemer/nexusai</div></div><div class="record-row"><div class="row-title">Safety boundary</div><div class="row-meta">GitHub Actions deployment is separate from NexusAI approval records. NexusAI does not run commands.</div></div></div>`; }
function messageRow(item) { return `<button class="record-row" onclick="openMessage(${item.id})"><span>${riskBadge(item.risk_level, item)}${statusPill(item.status)}</span><div class="row-title">${esc(item.from)} → ${esc(item.to)}: ${esc(item.subject)}</div><div class="row-meta">${esc(truncate(item.body))}</div></button>`; }
function taskRow(item) { return `<button class="record-row" onclick="openTask(${item.id})"><span>${riskBadge(item.risk_level, item)}${statusPill(item.status)}</span><div class="row-title">${esc(item.title)}</div><div class="row-meta">${esc(item.assigned_to)} · ${esc(truncate(item.description))}</div></button>`; }
function approvalRow(item) { return `<button class="record-row" onclick="openApproval(${item.id})"><span>${riskBadge(item.risk_level, item)}${statusPill(item.status)}</span><div class="row-title">${esc(item.action_summary)}</div><div class="row-meta">Reason: ${esc(truncate(item.reason || 'No reason given'))}</div></button>`; }
function conversationRow(item) { return `<button class="record-row" onclick="openConversation(${item.id})"><span>${statusPill(item.status)}</span><div class="row-title">${esc(item.title)}</div><div class="row-meta">Turns ${esc(item.turn_count)} / ${esc(item.max_turns)} · ${esc(item.created_by)}</div></button>`; }
function reviewRow(item) { return `<button class="record-row" onclick="openReview(${item.id})"><span>${riskBadge(item.risk_level)}${statusPill(item.status)}</span><div class="row-title">${esc(item.title)}</div><div class="row-meta">${esc(item.requested_by)} → ${esc(item.reviewer)} · ${esc(truncate(item.body))}</div></button>`; }
function noticeRow(item) { return `<button class="record-row" onclick="openNotice(${item.id})"><span>${riskBadge(item.risk_level)}${statusPill(item.status)}</span><div class="row-title">${esc(item.service || item.source)}: ${esc(item.title)}</div><div class="row-meta">${esc(truncate(item.body))}</div></button>`; }
function logLines(items) { return items.length ? items.map(l => `<div>${esc(l.timestamp)} ${esc(l.actor)} ${esc(l.summary)}</div>`).join('') : '<p class="empty-state">No audit log entries yet.</p>'; }

async function pageMessages() {
  const [items, approvals, notices] = await Promise.all([api('/messages'), api('/approvals'), api('/notices')]);
  const selected = items[0];
  page('Inbox / Command Center', 'Homepage focused on conversations, queues, and selected item detail.', `
    <form class="grid" onsubmit="createMessage(event)">
      ${select('from', participants, 'Mira')}${select('to', participants, 'Cameron')}
      <input name="subject" placeholder="Subject" required>
      ${select('risk_level', riskLevels, 'DOCUMENTATION ONLY')}
      <textarea name="body" placeholder="Message body" required></textarea>
      ${select('status', messageStatuses, 'delivered')}
      <button>+ New Message</button>
    </form>
    <div class="command-layout">
      <section class="wire-card"><h2>Queues</h2><div class="queue-list">
        <div class="queue-item"><span>Cameron Inbox</span><span>(${items.filter(i => i.to === 'Cameron' && !['archived','completed'].includes(i.status)).length})</span></div>
        <div class="queue-item"><span>Pending Approvals</span><span>(${approvals.filter(i => i.status === 'pending').length})</span></div>
        <div class="queue-item"><span>AI-to-AI Pending</span><span>(${items.filter(i => i.status === 'pending_approval').length})</span></div>
        <div class="queue-item"><span>System Notices</span><span>(${notices.filter(i => i.status === 'active').length})</span></div>
        <div class="recent-list"><strong>Recent</strong>${recordList(items.slice(0, 8), i => `<button class="record-row" onclick="openMessage(${i.id})">${esc(i.from)}: ${esc(i.subject)}</button>`)}</div>
      </div></section>
      <section class="wire-card"><h2>Selected Message</h2><div class="detail-shell">${selected ? messageDetailHtml(selected) : '<p class="empty-state">No selected message.</p>'}</div></section>
    </div>
    <section class="section-card wide" style="margin-top:28px"><h2>Pending Approval Strip</h2><div class="section-body">${approvals.filter(a => a.status === 'pending').map(a => `<button class="linkish" onclick="openApproval(${a.id})">${esc(a.requested_by)} requests ${esc(a.action_type)}</button>`).join(' &nbsp;|&nbsp; ') || 'No pending approvals.'}</div></section>`);
}
function messageDetailHtml(item) { return `
  <p>From: ${esc(item.from)}</p><p>To: ${esc(item.to)}</p><p>${riskBadge(item.risk_level)}${statusPill(item.status)}</p>
  <h3>Subject: ${esc(item.subject)}</h3>
  <h3>Full body</h3><div class="detail-box tall">${esc(item.body)}</div>
  <div class="detail-actions">
    ${actionButton('Acknowledge', `patchStatus('messages', ${item.id}, 'acknowledged')`)}
    ${actionButton('Create Task', `prefillTaskFromMessage(${item.id})`)}
    ${actionButton('Request Review', `prefillReviewFromMessage(${item.id})`)}
    ${actionButton('Archive', `patchStatus('messages', ${item.id}, 'archived')`)}
  </div>`; }
async function openMessage(id) { const item = await api(`/messages/${id}`); page('Message Detail View', 'Shows sender, recipient, status, risk, full message, and safe follow-up actions.', `<section class="detail-card"><h2>Message #${item.id} - ${esc(item.subject)}</h2><div class="detail-card-body">${messageDetailHtml(item)}</div></section>`); }
async function createMessage(event) { event.preventDefault(); await api('/messages', {method:'POST', body: JSON.stringify(formData(event))}); route(); }
function prefillTaskFromMessage(id) { window.location.href = `/tasks?from_message=${id}`; }
function prefillReviewFromMessage(id) { window.location.href = `/reviews?from_message=${id}`; }

async function pageTasks() {
  const items = await api('/tasks');
  page('Tasks', 'Tasks can be assigned, opened, started, blocked, completed, archived, and audited.', `
    <form class="grid" onsubmit="createTask(event)">
      <input name="title" placeholder="Title" required><textarea name="description" placeholder="Description" required></textarea>
      ${select('created_by', participants, 'Cameron')}${select('assigned_to', participants, 'Hermes')}
      ${select('risk_level', riskLevels, 'BUILD / UI')}${select('status', taskStatuses, 'open')}
      <button>Create Task</button>
    </form>
    ${table(items, [{label:'Open', render:i=>`<button class="compact" onclick="openTask(${i.id})">Open</button>`},{label:'Title', render:i=>`<strong>${esc(i.title)}</strong>`},{label:'Assigned', key:'assigned_to'},{label:'Risk', render:i=>riskBadge(i.risk_level)},{label:'Status', render:i=>statusPill(i.status)},{label:'Description', render:i=>esc(truncate(i.description))}])}`);
}
async function openTask(id) {
  const [item, logs] = await Promise.all([api(`/tasks/${id}`), api('/logs')]);
  const history = logs.filter(l => l.target_type === 'task' && Number(l.target_id) === Number(id));
  page('Task Detail View', 'Shows full task description, status, assignment, notes, and action history.', `
    <div class="detail-page-grid">
      <section class="detail-card"><h2>Task #${item.id} - ${esc(item.title)}</h2><div class="detail-card-body">
        <p>Created by: ${esc(item.created_by)}</p><p>Assigned to: ${esc(item.assigned_to)}</p><p>Status: ${esc(titleize(item.status))}</p><p>${riskBadge(item.risk_level)}</p>
        <h3>Full description</h3><div class="detail-box tall">${esc(item.description)}</div>
        <h3>Completion Notes</h3><textarea id="completion-notes" class="detail-box">${esc(item.completion_notes)}</textarea>
        <h3>Blocked Reason</h3><textarea id="blocked-reason" class="detail-box">${esc(item.blocked_reason)}</textarea>
        <div class="detail-actions">
          ${actionButton('Start', `patchTask(${item.id}, 'in_progress')`)}
          ${actionButton('Block', `patchTask(${item.id}, 'blocked')`)}
          ${actionButton('Complete', `patchTask(${item.id}, 'completed')`)}
          ${actionButton('Archive', `patchTask(${item.id}, 'archived')`)}
        </div>
      </div></section>
      <section class="detail-card"><h2>Action History</h2><div class="detail-card-body history-list">${logLines(history)}<br><br>Future:<br>Hermes submits change report<br>Cameron marks complete</div></section>
    </div>`);
}
async function createTask(event) { event.preventDefault(); await api('/tasks', {method:'POST', body: JSON.stringify(formData(event))}); route(); }
async function patchTask(id, status) { await api(`/tasks/${id}`, {method:'PATCH', body: JSON.stringify({status, completion_notes: document.querySelector('#completion-notes')?.value || '', blocked_reason: document.querySelector('#blocked-reason')?.value || ''})}); openTask(id); }

async function pageApprovals() {
  const items = await api('/approvals');
  page('Approvals', 'Approval requests record human decisions. Approval does not execute the action.', `
    <p class="notice strong">Safety warning: Approval records permission only. NexusAI will not execute proposed commands.</p>
    <form class="grid" onsubmit="createApproval(event)">
      ${select('requested_by', participants, 'Hermes')}${select('requested_for', participants, 'Cameron')}
      <input name="action_summary" placeholder="Action summary" required>${select('risk_level', riskLevels, 'STATE-CHANGING / APPROVAL REQUIRED')}
      <textarea name="proposed_command" placeholder="Proposed Command - text only"></textarea><textarea name="reason" placeholder="Reason"></textarea>
      ${select('status', approvalStatuses, 'pending')}<button>Create Approval Request</button>
    </form>
    ${table(items, [{label:'Open', render:i=>`<button class="compact" onclick="openApproval(${i.id})">Open</button>`},{label:'Action', key:'action_summary'},{label:'Requested By', key:'requested_by'},{label:'For', key:'requested_for'},{label:'Risk', render:i=>riskBadge(i.risk_level)},{label:'Status', render:i=>statusPill(i.status)}])}`);
}
async function openApproval(id) {
  const item = await api(`/approvals/${id}`);
  page('Approval Detail View', 'Focused on safe human review before any action is taken.', `
    <section class="detail-card"><h2>Approval Request #${item.id}</h2><div class="detail-card-body">
      <p>Requested by: ${esc(item.requested_by)}</p><p>Requested for: ${esc(item.requested_for)}</p><p>Status: ${esc(titleize(item.status))}</p><p>${riskBadge(item.risk_level)}</p>
      <h3>Action Summary</h3><div class="detail-box">${esc(item.action_summary)}</div>
      <h3>Reason</h3><div class="detail-box">${esc(item.reason)}</div>
      <h3>Proposed command / action text - text only</h3><pre class="detail-box command-text">${esc(item.proposed_command || '—')}</pre>
      <div class="safety-warning">Safety warning: Approval records permission only. NexusAI will not execute this command.</div>
      <div class="detail-actions">
        ${actionButton('Approve', `patchApproval(${item.id}, 'approved')`)}
        ${actionButton('Reject', `patchApproval(${item.id}, 'rejected')`)}
        ${actionButton('Archive', `patchApproval(${item.id}, 'archived')`)}
      </div>
    </div></section>`);
}
async function createApproval(event) { event.preventDefault(); await api('/approvals', {method:'POST', body: JSON.stringify(formData(event))}); route(); }
async function patchApproval(id, status) {
  const item = await api(`/approvals/${id}`, {method:'PATCH', body: JSON.stringify({status, approved_by:'Cameron', decision_notes:`Cameron marked ${status}.`})});
  page('Approval Updated', `Approval #${id} was marked ${status}.`, `<div class="feedback">Decision recorded. Approval does not equal execution.</div><section class="detail-card"><h2>Approval Request #${item.id}</h2><div class="detail-card-body"><p>Status: ${esc(titleize(item.status))}</p><p>Requested by: ${esc(item.requested_by)}</p><p>For: ${esc(item.requested_for)}</p><div class="detail-actions">${actionButton('Back to approval detail', `openApproval(${item.id})`)}${actionButton('Approval queue', `window.location.href='/approvals'`)}</div></div></section>`);
}

async function pageReviews() {
  const items = await api('/reviews');
  page('Reviews', 'Review requests let agents and people ask for architecture, code, documentation, and risk feedback.', `
    <form class="grid" onsubmit="createReview(event)">
      <input name="title" placeholder="Review title" required><textarea name="body" placeholder="Review request body" required></textarea>
      ${select('requested_by', participants, 'Hermes')}${select('reviewer', participants, 'Nova')}
      <input name="target_type" placeholder="Target type" value="documentation"><input name="target_ref" placeholder="Target reference">
      ${select('risk_level', riskLevels, 'REVIEW')}${select('status', reviewStatuses, 'open')}<button>Create Review Request</button>
    </form>${table(items, [{label:'Open', render:i=>`<button class="compact" onclick="openReview(${i.id})">Open</button>`},{label:'Title', key:'title'},{label:'Requested By', key:'requested_by'},{label:'Reviewer', key:'reviewer'},{label:'Risk', render:i=>riskBadge(i.risk_level)},{label:'Status', render:i=>statusPill(i.status)}])}`);
}
async function openReview(id) { const item = await api(`/reviews/${id}`); page('Review Detail View', 'Focused on review notes, target references, and recorded status.', `<section class="detail-card"><h2>Review Request #${item.id} - ${esc(item.title)}</h2><div class="detail-card-body"><p>${riskBadge(item.risk_level)}${statusPill(item.status)}</p><p>Requested by: ${esc(item.requested_by)}</p><p>Reviewer: ${esc(item.reviewer)}</p><p>Target: ${esc(item.target_type)} ${esc(item.target_ref)}</p><h3>Request</h3><div class="detail-box tall">${esc(item.body)}</div><h3>Review Notes</h3><textarea id="review-notes" class="detail-box">${esc(item.review_notes)}</textarea><div class="detail-actions">${actionButton('Start', `patchReview(${item.id}, 'in_progress')`)}${actionButton('Complete', `patchReview(${item.id}, 'completed')`)}${actionButton('Archive', `patchReview(${item.id}, 'archived')`)}</div></div></section>`); }
async function createReview(event) { event.preventDefault(); await api('/reviews', {method:'POST', body: JSON.stringify(formData(event))}); route(); }
async function patchReview(id, status) { await api(`/reviews/${id}`, {method:'PATCH', body: JSON.stringify({status, review_notes: document.querySelector('#review-notes')?.value || ''})}); openReview(id); }

async function pageNotices() {
  const items = await api('/notices');
  page('System Notices', 'Services create notices for outages, recovery, warnings, and scheduled maintenance.', `
    <form class="grid" onsubmit="createNotice(event)">
      <input name="service" placeholder="Service" value="Uptime Kuma"><input name="source" placeholder="Source" value="System">
      <input name="severity" placeholder="Severity" value="warning"><input name="title" placeholder="Title" required>
      <textarea name="body" placeholder="Notice body" required></textarea>${select('risk_level', riskLevels, 'WARNING')}${select('status', noticeStatuses, 'active')}<button>Create Notice</button>
    </form>${table(items, [{label:'Open', render:i=>`<button class="compact" onclick="openNotice(${i.id})">Open</button>`},{label:'Service', key:'service'},{label:'Title', key:'title'},{label:'Severity', key:'severity'},{label:'Risk', render:i=>riskBadge(i.risk_level)},{label:'Status', render:i=>statusPill(i.status)}])}`);
}
async function openNotice(id) { const item = await api(`/notices/${id}`); page('Notice Detail View', 'Focused on service events and monitor history. Notices do not execute remediation.', `<section class="detail-card"><h2>Notice #${item.id} - ${esc(item.title)}</h2><div class="detail-card-body"><p>Service: ${esc(item.service)}</p><p>Source: ${esc(item.source)}</p><p>Severity: ${esc(item.severity)}</p><p>${riskBadge(item.risk_level)}${statusPill(item.status)}</p><h3>Body</h3><div class="detail-box tall">${esc(item.body)}</div><div class="detail-actions">${actionButton('Acknowledge', `patchNotice(${item.id}, 'acknowledged')`)}${actionButton('Resolve', `patchNotice(${item.id}, 'resolved')`)}${actionButton('Archive', `patchNotice(${item.id}, 'archived')`)}</div></div></section>`); }
async function createNotice(event) { event.preventDefault(); await api('/notices', {method:'POST', body: JSON.stringify(formData(event))}); route(); }
async function patchNotice(id, status) { await api(`/notices/${id}`, {method:'PATCH', body: JSON.stringify({status})}); openNotice(id); }

async function pageServices() { const items = await api('/services'); page('Services', 'Internal systems and applications that NexusAI tracks or receives notices from.', table(items, [{label:'Name', key:'name'},{label:'Type', key:'service_type'},{label:'URL', key:'url'},{label:'Host', key:'host'},{label:'Notes', key:'notes'},{label:'Active', render:i=> i.is_active ? 'yes' : 'no'}])); }
async function pageConversations() { const items = await api('/conversations'); page('Conversation Threads', 'Read AI-to-AI exchanges as timelines with turn counts and approval state.', table(items, [{label:'Open', render:i=>`<button class="compact" onclick="openConversation(${i.id})">Timeline</button>`},{label:'Title', key:'title'},{label:'Status', render:i=>statusPill(i.status)},{label:'Created By', key:'created_by'},{label:'Turns', render:i=>`${esc(i.turn_count)} / ${esc(i.max_turns)}`},{label:'Summary', render:i=>esc(truncate(i.summary || ''))}])); }
async function openConversation(id) {
  const [conv, messages] = await Promise.all([api(`/conversations/${id}`), api(`/conversations/${id}/messages`)]);
  const timeline = messages.map(m => `<div class="timeline-item ${m.status === 'pending_approval' ? 'pending' : ''}"><div class="timeline-meta">${esc(m.created_at)} · ${esc(m.from)} → ${esc(m.to)} · ${statusPill(m.status)} ${riskBadge(m.risk_level, m)}</div><strong>${esc(m.subject)}</strong><div>${esc(m.body)}</div></div>`).join('') || '<p class="empty-state">No messages in this conversation.</p>';
  page('Conversation Timeline', `${conv.title} · ${conv.status} · turns ${conv.turn_count}/${conv.max_turns}`, `<section class="detail-card"><h2>Conversation #${conv.id}</h2><div class="detail-card-body"><p>Created by: ${esc(conv.created_by)}</p><p>Status: ${esc(titleize(conv.status))}</p><p>Summary: ${esc(conv.summary || '—')}</p><div class="timeline">${timeline}</div></div></section>`);
}
async function pageParticipants() { const items = await api('/participants'); page('Participants', 'Humans, AI assistants, services, and system identities that create, receive, or are assigned NexusAI records.', table(items, [{label:'Display Name', key:'display_name'},{label:'Type', key:'participant_type'},{label:'Role', key:'role_description'},{label:'Active', render:i=> i.is_active ? 'yes' : 'no'}])); }
async function pageLogs() { const items = await api('/logs'); page('Action Log', 'Append-only audit history. Meaningful activity inside NexusAI creates a log entry.', table(items, [{label:'Time', key:'timestamp'},{label:'Actor', key:'actor'},{label:'Action', key:'action_type'},{label:'Entity', render:i=>`${esc(i.target_type)} #${esc(i.target_id ?? '')}`},{label:'Summary', key:'summary'}])); }
async function patchStatus(type, id, status) { await api(`/${type}/${id}`, {method:'PATCH', body: JSON.stringify({status})}); route(); }

async function route() {
  try {
    const path = window.location.pathname;
    if (path === '/messages') return pageMessages();
    if (path === '/conversations') return pageConversations();
    if (path === '/tasks') return pageTasks();
    if (path === '/approvals') return pageApprovals();
    if (path === '/reviews') return pageReviews();
    if (path === '/notices') return pageNotices();
    if (path === '/services') return pageServices();
    if (path === '/participants' || path === '/agents') return pageParticipants();
    if (path === '/logs') return pageLogs();
    return dashboard();
  } catch (err) { page('Error', 'NexusAI could not render this view.', `<pre>${esc(err.stack || err.message || err)}</pre>`); }
}
route();
