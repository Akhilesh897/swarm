# API Guide

## POST /auth/login
Request:
```json
{
  "email": "employee@company.com",
  "password": "ChangeMe123!"
}
```

Response:
```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "user_id": "emp001",
  "role": "employee",
  "department": "hr"
}
```

## POST /auth/signup
Request:
```json
{
  "email": "new.user@example.com",
  "password": "secret1"
}
```

Response matches `/auth/login`. Newly signed up users receive the `employee` role unless their email is mapped in `ADMIN_EMAIL_ROLES`.

## GET /auth/next
Header:
```http
Authorization: Bearer <access_token>
```

Response:
```json
{
  "path": "/employee",
  "role": "employee"
}
```

## POST /chat
Header:
```http
Authorization: Bearer <access_token>
```

Request:
```json
{
  "query": "Apply leave for 2 days next week",
  "session_id": "s1",
  "model_preference": "auto"
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
