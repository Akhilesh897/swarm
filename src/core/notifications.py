from typing import Any

import httpx


REQUEST_DETAIL_KEYS = (
    "asset_type",
    "ticket_issue_type",
    "priority",
    "description",
    "leave_type",
    "start_date",
    "end_date",
)


def build_approval_notification_payload(
    *,
    event: str,
    entity_type: str | None,
    entity_id: int | str | None,
    approval_id: int | None,
    approval_stage: str | None,
    approval_status: str | None,
    requested_by_user_id: str,
    approver_role: str,
    approver_email: str,
    request_details: dict[str, Any] | None = None,
    requested_by_email: str | None = None,
    requested_by_name: str | None = None,
    requested_by_department: str | None = None,
) -> dict[str, Any]:
    details = dict.fromkeys(REQUEST_DETAIL_KEYS, None)
    if request_details:
        details.update({key: request_details.get(key) for key in REQUEST_DETAIL_KEYS if key in request_details})

    return {
        "event": event,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "approval_id": approval_id,
        "approval_stage": approval_stage,
        "approval_status": approval_status,
        "requested_by": {
            "user_id": requested_by_user_id,
            "email": requested_by_email,
            "name": requested_by_name,
            "department": requested_by_department,
        },
        "routing": {
            "approver_role": approver_role,
            "approver_email": approver_email,
        },
        "request_details": details,
    }


def send_power_automate_notification(url: str | None, payload: dict[str, Any]) -> None:
    print(f"[DEBUG] Power Automate notification triggered")
    print(f"[DEBUG] URL configured: {bool(url)}")
    if not url:
        print("[DEBUG] Power Automate URL not configured - skipping notification")
        return
    
    print(f"[DEBUG] Sending to Power Automate URL: {url}")
    print(f"[DEBUG] Payload: {payload}")
    
    try:
        response = httpx.post(url, json=payload, timeout=10)
        print(f"[DEBUG] Power Automate response status: {response.status_code}")
        print(f"[DEBUG] Power Automate response body: {response.text}")
        if response.status_code == 200:
            print("[DEBUG] Power Automate notification sent successfully")
        else:
            print(f"[DEBUG] Power Automate notification failed with status {response.status_code}")
    except httpx.HTTPError as exc:
        print(f"[DEBUG] Power Automate HTTP error: {exc}")
    except Exception as exc:
        print(f"[DEBUG] Power Automate unexpected error: {exc}")
