# Future: Real Jira board integration

## Intent
Replace or sync the Ampcus Helpdesk **Escalations Kanban MVP** with a real Atlassian Jira board so helpdesk high-severity / escalation tickets appear as Jira issues (stories) and workflow mirrors Jira columns.

## Current MVP (local board)
- UI Kanban columns map to ticket statuses: `open` → To Do, `assigned` → In Progress, `resolved` → Done
- Data lives in local `tickets.json` (`ticket_type=escalation`)
- `BoardMonitorAgent` polls unresolved board items and emails admins once after `ESCALATION_REMINDER_HOURS` (default 2)

## Planned integration
1. Configure Jira Cloud/Server: base URL, project key, API token, board/sprint id
2. On escalation create → create Jira issue (labels: department, severity, helpdesk ticket id)
3. Sync status both ways (webhook or poll): Jira transitions ↔ Helpdesk ticket status
4. Point `BoardMonitorAgent` at Jira “unresolved past SLA” instead of (or in addition to) local tickets
5. Keep Helpdesk board as a mirror or deep-link into Jira issue keys

## Non-goals for MVP
- Live Jira OAuth / webhooks
- Full Jira field mapping (epics, story points, sprints)
