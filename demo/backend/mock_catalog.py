"""Mock MCP servers: hand-written tool definitions and canned payloads.

Thirteen simulated servers (GitHub, Jira, Confluence, Slack, BigQuery, Cloud Storage, Calendar,
Outlook, ServiceNow, Datadog/PagerDuty, Connected Vehicle, Filesystem, Web). Replace any of them
with a real server's `tools/list` output in real_catalog/ (see real_catalog/build.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

S, I, B, A = "string", "integer", "boolean", "array"


@dataclass
class Tool:
    server: str
    name: str
    description: str
    params: Dict[str, tuple]          # pname -> (type, description, required)
    sample: Any = None

    @property
    def qualified(self) -> str:
        return f"{self.server}__{self.name}"

    def input_schema(self) -> Dict[str, Any]:
        props, req = {}, []
        for p, (t, d, r) in self.params.items():
            props[p] = {"type": t, "description": d}
            if t == A:
                props[p]["items"] = {"type": "string"}
            if r:
                req.append(p)
        return {"type": "object", "properties": props, "required": req}

    def anthropic_spec(self) -> Dict[str, Any]:
        return {"name": self.qualified,
                "description": f"[{self.server} MCP] {self.description}",
                "input_schema": self.input_schema()}


@dataclass
class Server:
    name: str
    title: str
    description: str
    tools: List[Tool] = field(default_factory=list)


def _srv(name, title, description, tools):
    s = Server(name, title, description)
    s.tools = [Tool(name, *t) for t in tools]
    return s


SERVERS: List[Server] = [
    _srv("github", "GitHub", "source code repositories, pull requests, commits, CI workflow runs", [
        ("search_repositories", "Search GitHub repositories by keyword, language, topic or owner.",
         {"query": (S, "Search keywords, supports GitHub qualifiers like language:python", True),
          "per_page": (I, "Results per page (max 100)", False)},
         {"total": 3, "items": ["acme/telemetry-ingest", "acme/fleet-api", "acme/dtc-decoder"]}),
        ("get_file_contents", "Read the contents of a file or directory from a GitHub repository at a ref.",
         {"owner": (S, "Repository owner", True), "repo": (S, "Repository name", True),
          "path": (S, "Path to the file", True), "ref": (S, "Branch, tag or commit SHA", False)},
         {"path": "README.md", "content": "# fleet-api\nREST service for fleet telemetry..."}),
        ("list_pull_requests", "List pull requests in a repository, filtered by state, author or base branch.",
         {"owner": (S, "Repository owner", True), "repo": (S, "Repository name", True),
          "state": (S, "open, closed or all", False), "base": (S, "Base branch filter", False)},
         [{"number": 412, "title": "Add DTC severity mapping", "author": "jdoe", "state": "open"},
          {"number": 409, "title": "Bump fastapi to 0.115", "author": "dependabot", "state": "open"}]),
        ("create_pull_request", "Open a new pull request from a head branch into a base branch.",
         {"owner": (S, "Repository owner", True), "repo": (S, "Repository name", True),
          "title": (S, "PR title", True), "head": (S, "Source branch", True), "base": (S, "Target branch", True),
          "body": (S, "PR description in markdown", False)},
         {"number": 413, "url": "https://github.example/acme/fleet-api/pull/413"}),
        ("create_issue", "Create a GitHub issue in a repository with labels and assignees.",
         {"owner": (S, "Repository owner", True), "repo": (S, "Repository name", True),
          "title": (S, "Issue title", True), "body": (S, "Issue body", False), "labels": (A, "Labels", False)},
         {"number": 88, "url": "https://github.example/acme/fleet-api/issues/88"}),
        ("list_commits", "List recent commits on a branch with author, message and SHA.",
         {"owner": (S, "Repository owner", True), "repo": (S, "Repository name", True),
          "sha": (S, "Branch or SHA to start from", False), "since": (S, "ISO8601 timestamp", False)},
         [{"sha": "a1b2c3d", "message": "Fix null VIN handling", "author": "asmith"}]),
        ("get_workflow_runs", "Get GitHub Actions CI workflow runs and their pass/fail status for a repository.",
         {"owner": (S, "Repository owner", True), "repo": (S, "Repository name", True),
          "branch": (S, "Branch filter", False), "status": (S, "completed, failure, success", False)},
         [{"id": 9911, "name": "ci", "branch": "main", "conclusion": "failure", "failed_step": "pytest"}]),
        ("search_code", "Search source code across repositories for symbols, functions or text.",
         {"query": (S, "Code search query", True), "repo": (S, "Restrict to owner/repo", False)},
         [{"path": "app/telemetry/ingest.py", "repo": "acme/fleet-api"}]),
        ("merge_pull_request", "Merge an open pull request using merge, squash or rebase.",
         {"owner": (S, "Repository owner", True), "repo": (S, "Repository name", True),
          "pull_number": (I, "PR number", True), "merge_method": (S, "merge, squash or rebase", False)},
         {"merged": True, "sha": "f00ba47"}),
    ]),
    _srv("jira", "Jira", "agile issue tracking: tickets, stories, bugs, sprints, boards, epics", [
        ("search_issues", "Search Jira issues using a JQL query.",
         {"jql": (S, "JQL query string", True), "max_results": (I, "Max issues to return", False),
          "fields": (A, "Fields to include", False)},
         [{"key": "FLEET-231", "summary": "Telemetry gaps for EV pickup fleet", "status": "In Progress"},
          {"key": "FLEET-219", "summary": "DTC P0A80 false positives", "status": "To Do"}]),
        ("get_issue", "Get full details of a single Jira issue by key, including description and comments.",
         {"issue_key": (S, "Issue key, e.g. PROJ-123", True)},
         {"key": "FLEET-231", "status": "In Progress", "assignee": "Priya N", "priority": "High"}),
        ("create_issue", "Create a new Jira issue (story, bug, task) in a project.",
         {"project_key": (S, "Project key", True), "summary": (S, "Summary", True),
          "issue_type": (S, "Story, Bug, Task or Epic", True), "description": (S, "Description", False),
          "priority": (S, "Priority", False)},
         {"key": "FLEET-240", "url": "https://jira.example/browse/FLEET-240"}),
        ("transition_issue", "Move a Jira issue to another workflow status such as In Progress or Done.",
         {"issue_key": (S, "Issue key", True), "status": (S, "Target status name", True)},
         {"key": "FLEET-231", "status": "Done"}),
        ("add_comment", "Add a comment to an existing Jira issue.",
         {"issue_key": (S, "Issue key", True), "body": (S, "Comment text", True)},
         {"id": "10442", "created": "2026-11-16T10:02:00Z"}),
        ("assign_issue", "Assign a Jira issue to a user.",
         {"issue_key": (S, "Issue key", True), "assignee": (S, "User id or email", True)},
         {"key": "FLEET-231", "assignee": "jdoe"}),
        ("list_sprints", "List active and future sprints for a Jira board.",
         {"board_id": (I, "Board id", True), "state": (S, "active, future or closed", False)},
         [{"id": 77, "name": "Sprint 46", "state": "active", "ends": "2026-11-21"}]),
        ("get_board", "Get a Jira agile board configuration and its columns.",
         {"board_id": (I, "Board id", True)},
         {"id": 12, "name": "Fleet Platform", "columns": ["To Do", "In Progress", "Review", "Done"]}),
    ]),
    _srv("confluence", "Confluence", "team wiki documentation pages, runbooks, design docs, spaces", [
        ("search_pages", "Search Confluence wiki pages using CQL or free text.",
         {"query": (S, "Free text or CQL", True), "space_key": (S, "Restrict to a space", False),
          "limit": (I, "Max results", False)},
         [{"id": "5501", "title": "Fleet API on-call runbook", "space": "FLEET"}]),
        ("get_page", "Get the body content of a Confluence page by id.",
         {"page_id": (S, "Page id", True), "expand": (S, "Fields to expand", False)},
         {"id": "5501", "title": "Fleet API on-call runbook", "body": "1. Check the monitoring dashboard..."}),
        ("create_page", "Create a new Confluence page in a space.",
         {"space_key": (S, "Space key", True), "title": (S, "Title", True),
          "body": (S, "Storage-format body", True), "parent_id": (S, "Parent page id", False)},
         {"id": "5620", "url": "https://confluence.example/pages/5620"}),
        ("update_page", "Update the content of an existing Confluence page.",
         {"page_id": (S, "Page id", True), "body": (S, "New body", True), "version": (I, "Current version", True)},
         {"id": "5501", "version": 14}),
        ("list_spaces", "List Confluence spaces the user can access.",
         {"limit": (I, "Max results", False)}, [{"key": "FLEET", "name": "Fleet Platform"}]),
        ("get_page_children", "List child pages under a Confluence page.",
         {"page_id": (S, "Parent page id", True)}, [{"id": "5502", "title": "Escalation matrix"}]),
    ]),
    _srv("slack", "Slack", "team chat messaging: channels, direct messages, posting announcements", [
        ("post_message", "Post a message to a Slack channel or DM.",
         {"channel": (S, "Channel name or id", True), "text": (S, "Message text (mrkdwn)", True),
          "thread_ts": (S, "Reply in thread", False)},
         {"ok": True, "ts": "1763290000.0012"}),
        ("search_messages", "Search Slack message history across channels.",
         {"query": (S, "Search query", True), "count": (I, "Max results", False)},
         [{"channel": "#fleet-oncall", "user": "asmith", "text": "telemetry lag again on ingest-2"}]),
        ("list_channels", "List Slack channels in the workspace.",
         {"types": (S, "public_channel, private_channel", False)}, ["#fleet-oncall", "#fleet-platform"]),
        ("get_channel_history", "Get recent messages from a Slack channel.",
         {"channel": (S, "Channel id", True), "limit": (I, "Number of messages", False)},
         [{"user": "jdoe", "text": "Deploy of fleet-api 2.4 done"}]),
        ("add_reaction", "Add an emoji reaction to a Slack message.",
         {"channel": (S, "Channel id", True), "timestamp": (S, "Message ts", True), "name": (S, "Emoji", True)},
         {"ok": True}),
        ("create_channel", "Create a new Slack channel.",
         {"name": (S, "Channel name", True), "is_private": (B, "Private channel", False)},
         {"id": "C0912", "name": "inc-telemetry-lag"}),
        ("get_user_profile", "Get a Slack user's profile, title and timezone.",
         {"user": (S, "User id or email", True)}, {"name": "Priya N", "title": "SRE", "tz": "America/Detroit"}),
    ]),
    _srv("bigquery", "BigQuery", "data warehouse SQL analytics over tables and datasets", [
        ("list_datasets", "List BigQuery datasets in a GCP project.",
         {"project_id": (S, "GCP project", True)}, ["fleet_telemetry", "warranty", "dealer_ops"]),
        ("list_tables", "List tables in a BigQuery dataset.",
         {"project_id": (S, "GCP project", True), "dataset_id": (S, "Dataset", True)},
         ["vehicle_signals", "dtc_events", "trips"]),
        ("get_table_schema", "Get column names and types of a BigQuery table.",
         {"table": (S, "project.dataset.table", True)},
         [{"name": "vin", "type": "STRING"}, {"name": "dtc_code", "type": "STRING"},
          {"name": "event_ts", "type": "TIMESTAMP"}]),
        ("run_query", "Execute a GoogleSQL query in BigQuery and return rows.",
         {"sql": (S, "GoogleSQL query", True), "max_rows": (I, "Max rows", False)},
         {"rows": [{"model": "EV Pickup", "dtc_events": 1824}, {"model": "EV Crossover", "dtc_events": 1311}]}),
        ("dry_run_query", "Validate a BigQuery query and estimate bytes scanned without running it.",
         {"sql": (S, "GoogleSQL query", True)}, {"valid": True, "bytes_processed": 4821993472}),
        ("get_job", "Get status of a BigQuery job by id.",
         {"job_id": (S, "Job id", True)}, {"state": "DONE", "slot_ms": 82011}),
    ]),
    _srv("gcs", "Cloud Storage", "object storage buckets and files in Google Cloud Storage", [
        ("list_buckets", "List Cloud Storage buckets in a project.",
         {"project_id": (S, "GCP project", True)}, ["fleet-raw-landing", "fleet-exports"]),
        ("list_objects", "List objects in a GCS bucket under a prefix.",
         {"bucket": (S, "Bucket", True), "prefix": (S, "Prefix", False)},
         ["exports/2026-11-15/dtc.parquet"]),
        ("read_object", "Download and read the content of a GCS object.",
         {"bucket": (S, "Bucket", True), "object": (S, "Object path", True)}, {"size": 20311, "preview": "vin,code"}),
        ("upload_object", "Upload content to a GCS object.",
         {"bucket": (S, "Bucket", True), "object": (S, "Object path", True), "content": (S, "Content", True)},
         {"ok": True}),
        ("generate_signed_url", "Generate a time-limited signed URL to share a GCS object.",
         {"bucket": (S, "Bucket", True), "object": (S, "Object path", True), "expires_minutes": (I, "TTL", False)},
         {"url": "https://storage.example/signed/abc"}),
    ]),
    _srv("calendar", "Calendar", "meetings, calendar events, scheduling and availability", [
        ("list_events", "List calendar events in a time range.",
         {"start": (S, "ISO8601 start", True), "end": (S, "ISO8601 end", True), "calendar_id": (S, "Calendar", False)},
         [{"title": "Fleet platform sync", "start": "2026-11-17T10:00", "attendees": 6}]),
        ("create_event", "Create a calendar meeting invite with attendees.",
         {"title": (S, "Title", True), "start": (S, "ISO8601 start", True), "end": (S, "ISO8601 end", True),
          "attendees": (A, "Attendee emails", False), "location": (S, "Room or link", False)},
         {"id": "evt_771", "link": "https://meet.example/abc"}),
        ("find_free_slots", "Find common free time slots for a set of attendees.",
         {"attendees": (A, "Emails", True), "duration_minutes": (I, "Length", True), "within_days": (I, "Horizon", False)},
         [{"start": "2026-11-18T14:00", "end": "2026-11-18T14:30"}]),
        ("update_event", "Reschedule or edit an existing calendar event.",
         {"event_id": (S, "Event id", True), "start": (S, "New start", False), "end": (S, "New end", False)},
         {"ok": True}),
        ("delete_event", "Cancel and delete a calendar event.", {"event_id": (S, "Event id", True)}, {"ok": True}),
        ("respond_to_invite", "Accept, decline or tentatively accept a meeting invite.",
         {"event_id": (S, "Event id", True), "response": (S, "accepted, declined, tentative", True)}, {"ok": True}),
    ]),
    _srv("outlook", "Outlook Mail", "email inbox: reading, searching, sending and replying to email", [
        ("search_email", "Search the mailbox by sender, subject, keywords or date.",
         {"query": (S, "Search query", True), "folder": (S, "Folder", False), "top": (I, "Max results", False)},
         [{"id": "m1", "from": "vp.ops@example.com", "subject": "Q4 warranty review prep"}]),
        ("read_email", "Read the full body of an email message by id.",
         {"message_id": (S, "Message id", True)}, {"subject": "Q4 warranty review prep", "body": "Please bring..."}),
        ("send_email", "Send a new email message.",
         {"to": (A, "Recipients", True), "subject": (S, "Subject", True), "body": (S, "Body", True),
          "cc": (A, "CC", False)}, {"ok": True, "id": "m99"}),
        ("draft_reply", "Create a draft reply to an email without sending it.",
         {"message_id": (S, "Message id", True), "body": (S, "Reply body", True)}, {"draft_id": "d12"}),
        ("list_folders", "List mailbox folders.", {}, ["Inbox", "Archive", "Escalations"]),
        ("move_email", "Move an email to another folder.",
         {"message_id": (S, "Message id", True), "folder": (S, "Destination", True)}, {"ok": True}),
    ]),
    _srv("servicenow", "ServiceNow", "IT service management: incidents, change requests, knowledge base", [
        ("create_incident", "Open a new ServiceNow IT incident ticket.",
         {"short_description": (S, "Summary", True), "urgency": (I, "1-3", False),
          "assignment_group": (S, "Group", False), "description": (S, "Details", False)},
         {"number": "INC0049121"}),
        ("get_incident", "Get a ServiceNow incident by number.",
         {"number": (S, "Incident number", True)}, {"number": "INC0049121", "state": "In Progress"}),
        ("update_incident", "Update state, notes or assignee on a ServiceNow incident.",
         {"number": (S, "Incident number", True), "state": (S, "New state", False), "work_notes": (S, "Notes", False)},
         {"ok": True}),
        ("search_knowledge_base", "Search ServiceNow knowledge articles for IT how-to and fixes.",
         {"query": (S, "Query", True)}, [{"id": "KB0012", "title": "Reset VPN token"}]),
        ("create_change_request", "Raise a change request for a production deployment.",
         {"short_description": (S, "Summary", True), "risk": (S, "low, moderate, high", True),
          "planned_start": (S, "ISO8601", True)}, {"number": "CHG0003312"}),
        ("list_assigned_tickets", "List ServiceNow tickets assigned to me or my group.",
         {"assignee": (S, "User or group", False)}, [{"number": "INC0049102", "short": "VPN drops"}]),
    ]),
    _srv("observability", "Datadog / PagerDuty", "production monitoring: metrics, logs, alerts, on-call, incidents", [
        ("query_metrics", "Query a timeseries metric such as latency, error rate or CPU.",
         {"query": (S, "Metric query", True), "from": (S, "Start", True), "to": (S, "End", False)},
         {"series": "p95 latency", "points": [[0, 210], [1, 940], [2, 980]]}),
        ("search_logs", "Search application logs by service, status and text.",
         {"query": (S, "Log query", True), "from": (S, "Start", True), "limit": (I, "Max", False)},
         [{"service": "fleet-api", "status": "error", "msg": "timeout calling ingest-2"}]),
        ("list_monitors", "List configured monitors and their states.",
         {"tags": (A, "Tag filter", False)}, [{"name": "fleet-api p95", "state": "Alert"}]),
        ("get_active_alerts", "Get currently firing production alerts.",
         {"service": (S, "Service filter", False)}, [{"service": "fleet-api", "alert": "p95 > 800ms", "since": "09:12"}]),
        ("list_oncall", "Show who is on call right now for a schedule.",
         {"schedule": (S, "Schedule name", True)}, {"primary": "Priya N", "secondary": "Arun S"}),
        ("acknowledge_incident", "Acknowledge a PagerDuty incident to stop escalation.",
         {"incident_id": (S, "Incident id", True)}, {"ok": True}),
        ("get_dashboard", "Fetch a monitoring dashboard's widgets and current values.",
         {"dashboard_id": (S, "Dashboard id", True)}, {"title": "Fleet API", "widgets": 14}),
    ]),
    _srv("vehicle", "Connected Vehicle", "connected vehicle data: VIN status, diagnostic trouble codes, recalls, warranty, service", [
        ("get_vehicle_status", "Get live status of a vehicle by VIN: battery, odometer, location, software version.",
         {"vin": (S, "17-char VIN", True)},
         {"vin": "1ABCD23EFGH456789", "soc": 0.62, "odometer_km": 18211, "sw": "R07.4"}),
        ("get_dtc_codes", "Get active diagnostic trouble codes (DTCs) reported by a vehicle.",
         {"vin": (S, "VIN", True), "since": (S, "ISO8601", False)},
         [{"code": "P0A80", "desc": "Replace hybrid battery pack", "first_seen": "2026-11-12"}]),
        ("list_recalls_for_vin", "List open safety recalls and field service actions for a VIN.",
         {"vin": (S, "VIN", True)}, [{"id": "24S41", "title": "Rear axle bolt", "status": "Open"}]),
        ("get_warranty_claims", "Get warranty claim history for a VIN or model.",
         {"vin": (S, "VIN", False), "model": (S, "Model", False)}, [{"claim": "W-88121", "part": "HV battery", "cost": 4210}]),
        ("schedule_service_appointment", "Book a dealer service appointment for a vehicle.",
         {"vin": (S, "VIN", True), "dealer_code": (S, "Dealer", True), "date": (S, "Date", True)},
         {"confirmation": "SVC-55120"}),
        ("send_ota_update", "Schedule an over-the-air software update to a vehicle.",
         {"vin": (S, "VIN", True), "package": (S, "Software package", True)}, {"job": "OTA-7781", "state": "queued"}),
    ]),
    _srv("filesystem", "Filesystem", "local files and directories on disk", [
        ("read_file", "Read a text file from the local filesystem.", {"path": (S, "Path", True)}, {"content": "..."}),
        ("write_file", "Write or overwrite a local file.", {"path": (S, "Path", True), "content": (S, "Content", True)},
         {"ok": True}),
        ("list_directory", "List files in a local directory.", {"path": (S, "Path", True)}, ["report.md", "data.csv"]),
        ("search_files", "Find local files by glob pattern or content.",
         {"pattern": (S, "Glob or regex", True), "root": (S, "Root dir", False)}, ["./reports/q3.md"]),
        ("get_file_info", "Get size and modified time of a local file.", {"path": (S, "Path", True)}, {"size": 2048}),
    ]),
    _srv("web", "Web", "public internet search, news, weather and fetching web pages", [
        ("web_search", "Search the public web for news, facts and websites.",
         {"query": (S, "Query", True), "num_results": (I, "Count", False)},
         [{"title": "EV adoption hits record in Q3", "url": "https://news.example/ev-q3"}]),
        ("fetch_url", "Fetch and extract readable text from a web page URL.", {"url": (S, "URL", True)},
         {"title": "EV adoption hits record", "text": "Electric vehicle sales rose 18%..."}),
        ("get_weather", "Get current weather and forecast for a city.",
         {"location": (S, "City", True), "days": (I, "Forecast days", False)}, {"temp_c": 4, "conditions": "snow"}),
        ("currency_convert", "Convert an amount between currencies at today's rate.",
         {"amount": (I, "Amount", True), "from": (S, "ISO code", True), "to": (S, "ISO code", True)}, {"result": 0.94}),
    ]),
]

