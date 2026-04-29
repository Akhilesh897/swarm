# Agent Specifications

## Common Inputs
- user_id
- role
- query
- context (session memory)

## Common Outputs
- response_text
- tool_calls (optional)
- approval_required (optional)
- trace_id

## Router Agent
- Purpose: classify intent and route to a domain agent
- Tools: none
- Output: routed_agent, confidence

## HR Agent
- Purpose: policy QnA (RAG), leave workflows
- Tools: apply_leave, get_leave_balance, list_leave_history
- Data: HR policies, SQL leave tables
- Approval: leave above threshold

## IT Agent
- Purpose: IT support tickets and asset requests
- Tools: create_ticket, list_tickets, request_asset
- Data: SQL tickets, asset inventory
- Approval: asset requests

## Finance Agent
- Purpose: payslips, reimbursements, tax QnA
- Tools: fetch_payslip, submit_reimbursement, list_reimbursements
- Data: SQL finance tables, finance policy docs
- Approval: high value reimbursements

## RAG Agent
- Purpose: retrieve relevant documents for other agents
- Tools: vector_search
- Data: vector DB, file storage

## Approval Agent
- Purpose: route human approvals and capture decisions
- Tools: approve_request, get_approval_status
- Data: approvals table

## Email Agent
- Purpose: send outbound emails via Power Automate
- Tools: send_email
- Data: Power Automate webhook

## Analytics Agent
- Purpose: metrics and reporting
- Tools: list_metrics, log_event
- Data: logs table
