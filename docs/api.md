# API Guide

## POST /chat
Request:
```json
{
  "user_id": "u123",
  "role": "employee",
  "query": "Apply leave for 2 days next week",
  "session_id": "s1"
}
```

Response:
```json
{
  "response": "Leave request submitted. Awaiting approval.",
  "trace_id": "trace_abc123",
  "approval_required": true
}
```

## GET /health
Returns `ok` when service is up.

## POST /tools/*
Tool endpoints emulate MCP calls:
- /tools/apply_leave
- /tools/list_leave_history
- /tools/list_pending_leaves
- /tools/cancel_leave
- /tools/create_ticket
- /tools/get_leave_balance
- /tools/approve_request
- /tools/get_approval_status
- /tools/send_email
