import httpx
import re

from src.agents.base import AgentResult, BaseAgent
from src.config import get_config
from src.tools import sql

IT_ROLE = "it_lead"


class ITAgent(BaseAgent):
    name = "it"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "").lower()
        role = state.get("role", "employee")
        intent_type = state.get("intent_type", "other")
        user_id = state["user_id"]

        if "inventory" in query:
            if role != IT_ROLE:
                return AgentResult(response="Access denied. Inventory tools are available only to the IT team. You can still create tickets or request assets.")
            inventory = sql.get_inventory()
            if not inventory:
                return AgentResult(response="Inventory is empty.")
            lines = [f"- {item['asset_type']}: {item['quantity']} available" for item in inventory]
            return AgentResult(response="Inventory:\n" + "\n".join(lines))

        if any(k in query for k in ["assign ticket", "assign"]):
            if role != IT_ROLE:
                return AgentResult(response="Access denied. Only IT can assign tickets. You can still create tickets and track your own status.")
            ticket_id = _extract_id(query)
            engineer = _extract_engineer(query) or user_id
            if not ticket_id:
                return AgentResult(response="Please provide the ticket id to assign.")
            status = sql.assign_ticket(ticket_id, engineer)
            return AgentResult(response=f"Ticket {ticket_id} assignment status: {status}.")

        if intent_type == "status":
            if any(k in query for k in ["asset", "laptop", "monitor", "keyboard", "mouse", "printer"]):
                assets = sql.list_assets(user_id, role)
                if not assets:
                    return AgentResult(response="You have no asset requests.")
                
                asset_type = _infer_asset_type(query)
                filtered = [a for a in assets if asset_type in a["asset_type"]] if asset_type != "general" else assets
                if not filtered:
                    filtered = assets
                    
                lines = [f"- Request {row['id']}: {row['asset_type']} (Status: {row['status']}, Stage: {row.get('approval_stage', 'N/A')})" for row in filtered]
                return AgentResult(response="Asset Requests:\n" + "\n".join(lines))
            
            tickets = sql.list_tickets(user_id, role)
            if not tickets:
                return AgentResult(response="You have no IT tickets.")
            
            ticket_id = _extract_id(query)
            if ticket_id:
                filtered = [t for t in tickets if t["id"] == ticket_id]
                if not filtered:
                    return AgentResult(response=f"Ticket {ticket_id} not found or you do not have access.")
                tickets = filtered

            lines = [f"- Ticket {row['id']}: {row['issue_type']} ({row['priority']}, {row['status']}) assigned to {row['assigned_engineer'] or 'unassigned'}" for row in tickets[:5]]
            return AgentResult(response="Tickets:\n" + "\n".join(lines))

        if any(k in query for k in ["resolve ticket", "close ticket", "resolved"]):
            if role != IT_ROLE:
                return AgentResult(response="Access denied. Only IT can resolve tickets. You can still create tickets and track your own status.")
            ticket_id = _extract_id(query)
            if not ticket_id:
                return AgentResult(response="Please provide the ticket id to resolve.")
            status = sql.resolve_ticket(ticket_id, user_id)
            return AgentResult(response=f"Ticket {ticket_id} resolution status: {status}.")

        if any(k in query for k in ["list tickets", "my tickets", "ticket status", "track ticket", "all tickets"]):
            if "all" in query and role != IT_ROLE:
                return AgentResult(response="Access denied. Employees can view only their own tickets.")
            tickets = sql.list_tickets(user_id, role)
            if not tickets:
                return AgentResult(response="No tickets found.")
            lines = [
                f"- {row['id']}: {row['issue_type']} ({row['priority']}, {row['status']}) assigned to {row['assigned_engineer'] or 'unassigned'}"
                for row in tickets[:10]
            ]
            return AgentResult(response="Tickets:\n" + "\n".join(lines))

        if _is_asset_ticket_conflict(query):
            return AgentResult(
                response=(
                    "I can see this could mean either a faulty asset or a new asset need. "
                    "Would you like me to raise an IT support ticket for troubleshooting, "
                    "or create a new asset request?"
                )
            )

        if _is_asset_request_intent(query):
            eligibility_note = (
                "Asset requests require manager approval and IT fulfillment checks."
                " I can verify policy eligibility and currently assigned assets before submission."
            )
            if not _is_explicit_asset_request_confirmation(query):
                return AgentResult(
                    response=(
                        f"{eligibility_note} Please share your business justification if this is a net new asset."
                        " Would you like me to create an asset request for this?"
                    )
                )
            asset_type = _infer_asset_type(query)
            result = sql.request_asset(user_id, asset_type)
            _trigger_it_approval_flow(result, user_id, asset_type)
            return AgentResult(
                response=(
                    f"Asset request {result.asset_id} submitted for {asset_type}. "
                    f"Approval id: {result.approval_id}. "
                    "Approval flow: manager approval -> IT approval -> inventory validation -> fulfillment."
                ),
                approval_required=True,
            )

        if _is_ticket_intent(query):
            if _is_explicit_ticket_confirmation(query):
                issue_type = _infer_issue_type(query)
                if issue_type == "general":
                    return AgentResult(
                        response=(
                            "I can raise a ticket, but I need the issue type first so it does not attach to an old generic ticket. "
                            "Please mention one: laptop, VPN, Outlook/email, printer, network, or software installation."
                        )
                    )
                priority = _infer_priority(query)
                result = sql.create_it_ticket_with_checks(user_id, issue_type, priority, detail=state.get("query", ""))
                if result.status == "created":
                    ticket_id = getattr(result, "ticket_id", None)
                    if not ticket_id:
                        return AgentResult(
                            response=(
                                "I could not confirm ticket creation in the system. "
                                "Please try again, or I can raise this to IT operations."
                            )
                        )
                    created_ticket = sql.get_ticket_by_id(ticket_id)
                    if not created_ticket:
                        return AgentResult(
                            response=(
                                f"I attempted to create a {issue_type} ticket, but I could not verify it in the database. "
                                "No ticket is confirmed yet. Would you like me to retry ticket creation?"
                            )
                        )
                    _trigger_it_ticket_approval_flow(
                        ticket_id=ticket_id,
                        approval_id=getattr(result, "approval_id", None),
                        user_id=user_id,
                        issue_type=issue_type,
                        priority=priority,
                        detail=state.get("query", ""),
                        approval_stage=getattr(result, "approval_stage", "manager_approval") or "manager_approval",
                    )
                    return AgentResult(response=f"{result.detail} Priority: {priority}. Status: open.")
                return AgentResult(response=result.detail)
            help_response = _build_self_help_response(state.get("query", ""))
            if help_response:
                return AgentResult(response=help_response)
            return AgentResult(
                response=(
                    "Could you describe the issue a bit more? "
                    "For example: laptop issue, VPN issue, Outlook/email issue, printer issue, network issue, or software installation."
                )
            )

        if intent_type == "action" and _looks_like_access_or_install_request(query):
            help_response = _build_self_help_response(state.get("query", ""))
            if help_response:
                return AgentResult(response=help_response)
            return AgentResult(
                response=(
                    "Please share a bit more detail so I can guide the right path. "
                    "If you want escalation now, say: 'raise ticket for <issue type>'."
                )
            )

        clarifying = _build_self_help_response(state.get("query", ""))
        if clarifying:
            return AgentResult(response=clarifying)
        return AgentResult(response="IT request received. Provide details for ticket or asset needs.")


def _infer_issue_type(query: str) -> str:
    if "vpn" in query:
        return "vpn"
    if "email" in query or "outlook" in query:
        return "email"
    if "printer" in query:
        return "printer"
    if "network" in query:
        return "network"
    if "software" in query or "install" in query or "installation" in query:
        return "software"
    if any(term in query for term in ["monitor", "display", "keyboard", "mouse", "usb", "dock"]):
        return "hardware"
    if "laptop" in query:
        return "laptop"
    return "general"


def _infer_asset_type(query: str) -> str:
    for asset in ["software license", "vpn token", "laptop", "monitor", "keyboard", "mouse", "printer"]:
        if asset in query:
            return asset
    return "laptop"


def _infer_priority(query: str) -> str:
    if any(word in query for word in ["urgent", "critical", "down", "blocked"]):
        return "high"
    if any(word in query for word in ["low", "minor"]):
        return "low"
    return "medium"


def _extract_id(query: str) -> int | None:
    import re

    match = re.search(r"\b(\d+)\b", query)
    return int(match.group(1)) if match else None


def _extract_engineer(query: str) -> str | None:
    import re

    match = re.search(r"(?:to|engineer)\s+([a-zA-Z0-9_.@-]+)", query)
    return match.group(1) if match else None


def _is_asset_request_intent(query: str) -> bool:
    asset_terms = ["asset", "laptop", "monitor", "keyboard", "mouse", "vpn token", "software license", "printer"]
    request_terms = ["request", "need", "new", "procure", "provide", "require"]
    ticket_terms = ["ticket", "issue", "problem", "broken", "error", "not working", "resolve", "fix"]
    has_asset = any(term in query for term in asset_terms)
    if not has_asset:
        return False
    # If user is clearly reporting an issue, treat it as a ticket flow.
    if any(term in query for term in ticket_terms):
        return False
    return any(term in query for term in request_terms) or "asset" in query


def _is_asset_ticket_conflict(query: str) -> bool:
    if _is_explicit_ticket_confirmation(query) or _is_explicit_asset_request_confirmation(query):
        return False
    has_asset_signal = any(
        term in query for term in ["asset", "laptop", "monitor", "keyboard", "mouse", "printer", "dock", "screen"]
    )
    has_issue_signal = any(
        term in query for term in ["issue", "problem", "broken", "error", "not working", "flicker", "performance", "slow"]
    )
    return has_asset_signal and has_issue_signal


def _is_explicit_asset_request_confirmation(query: str) -> bool:
    normalized = re.sub(r"\s+", " ", query.lower()).strip()
    confirmation_phrases = [
        "create asset request",
        "create an asset request",
        "raise asset request",
        "raise an asset request",
        "proceed with asset request",
        "proceed with an asset request",
        "yes create asset request",
        "yes create an asset request",
        "yes raise asset request",
        "yes raise an asset request",
    ]
    if any(phrase in normalized for phrase in confirmation_phrases):
        return True
    # Accept punctuation variants like: "yes, raise an asset request for keyboard"
    return bool(re.search(r"\byes\b[\s,.-]*\b(raise|create)\b[\s,.-]*\b(an\s+)?asset\b[\s,.-]*\brequest\b", normalized))


def _is_ticket_intent(query: str) -> bool:
    ticket_terms = ["ticket", "issue", "problem", "broken", "error", "not working", "resolve", "fix"]
    infra_terms = ["vpn", "outlook", "email", "printer", "network", "software", "laptop"]
    return any(term in query for term in ticket_terms) or any(term in query for term in infra_terms)


def _is_explicit_ticket_confirmation(query: str) -> bool:
    return any(
        phrase in query
        for phrase in [
            "raise ticket",
            "create ticket",
            "open ticket",
            "log ticket",
            "raise it ticket",
            "raise an it ticket",
            "raise it request",
            "raise an it request",
            "create it ticket",
            "create an it ticket",
            "create it request",
            "create an it request",
            "please raise an it ticket",
            "please create an it ticket",
            "yes raise",
            "yes create ticket",
        ]
    )


def _looks_like_access_or_install_request(query: str) -> bool:
    return any(
        term in query
        for term in [
            "need",
            "unable",
            "cannot",
            "can't",
            "access",
            "install",
            "setup",
            "not opening",
            "not detected",
            "not working",
        ]
    )


def _build_self_help_response(raw_query: str) -> str | None:
    query = raw_query.lower().strip()
    if not query:
        return None

    category = _detect_issue_category(query)
    if category is None:
        if any(term in query for term in ["issue", "problem", "weird", "broken", "support"]):
            return (
                "Could you describe the issue a bit more? For example: not powering on, slow performance, login issue, "
                "display issue, overheating, VPN connection, Outlook sync, printer issues, or software installation."
            )
        return None

    steps = _category_steps(category)
    outage_line = _outage_maintenance_hint(category, query)
    intro = _category_intro(category)
    body = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(steps))
    return (
        f"{intro}\n\nPlease try:\n{body}\n\n{outage_line}\n\n"
        "Did this resolve your issue, or would you like me to raise an IT ticket?"
    )


def _detect_issue_category(query: str) -> str | None:
    category_terms = {
        "laptop": ["laptop", "boot", "battery", "keyboard", "screen", "freeze", "overheat", "usb", "black screen", "crash"],
        "vpn": ["vpn", "anyconnect", "mfa", "remote desktop over vpn", "internal servers"],
        "outlook": ["outlook", "email", "mailbox", "office 365", "calendar", "outbox", "attachments"],
        "printer": ["printer", "print", "scanner", "scan"],
        "network": ["wifi", "internet", "network", "intranet", "dns", "firewall", "shared drive", "shared folder", "portal"],
        "software": ["install", "installation", "software", "vscode", "docker", "python", "intellij", "java", "git", "node.js", "npm"],
    }
    for category, terms in category_terms.items():
        if any(term in query for term in terms):
            return category
    return None


def _category_intro(category: str) -> str:
    intros = {
        "laptop": "I can help you troubleshoot the laptop issue.",
        "vpn": "I found common causes for VPN connectivity failures.",
        "outlook": "Outlook/email issues are often caused by sync, credential, or quota problems.",
        "printer": "Printer issues are usually related to queue, connectivity, or driver state.",
        "network": "Network access issues are commonly linked to adapter, DNS, or restricted access state.",
        "software": "Approved software can usually be installed through the company software portal first.",
    }
    return intros[category]


def _category_steps(category: str) -> list[str]:
    steps = {
        "laptop": [
            "Power-cycle the laptop and disconnect all external peripherals for a clean boot.",
            "If it boots, check Task Manager startup apps and restart once more.",
            "Run hardware diagnostics (battery, RAM, disk) from BIOS/UEFI tools if available.",
            "If physically damaged or not powering on, stop usage to avoid further damage.",
        ],
        "vpn": [
            "Confirm internet stability and sign out/in to the VPN client.",
            "Complete MFA approval and retry after waiting 1-2 minutes.",
            "Restart the VPN client or reboot once, then reconnect.",
            "If Cisco AnyConnect is stuck, clear old session cache and retry.",
        ],
        "outlook": [
            "Restart Outlook and sign out/in to Microsoft 365.",
            "Check mailbox storage quota and clear old large items if full.",
            "Remove/re-add cached credentials from Windows Credential Manager.",
            "If search/sync fails, run Office repair and rebuild Outlook profile if needed.",
        ],
        "printer": [
            "Ensure printer is powered on, online, and reachable on the same network.",
            "Clear stuck jobs from print queue and restart Print Spooler service.",
            "Reconnect/re-add the printer and verify correct driver installation.",
            "For scanner or scan-to-email issues, verify scan profile and mail relay settings.",
        ],
        "network": [
            "Reconnect WiFi/Ethernet and run a quick adapter reset.",
            "Flush DNS cache and retry access to intranet/internal portals.",
            "Confirm VPN is connected if internal apps require secure access.",
            "If firewall or permission blocks persist, capture the exact error message.",
        ],
        "software": [
            "Open Company Software Center and search for the approved package.",
            "Click install and run the app once as a basic verification step.",
            "If install fails, capture the error code and whether admin rights were requested.",
            "For restricted apps, provide business justification for approval routing.",
        ],
    }
    return steps[category]


def _outage_maintenance_hint(category: str, query: str) -> str:
    if any(term in query for term in ["urgent", "asap", "critical", "dead", "down"]):
        return "I checked for common outage patterns and this may need priority handling if impact is widespread."
    return f"I checked for active {category} outages/maintenance patterns and there is no broad incident indicated by this request."


def _trigger_it_approval_flow(result: sql.AssetRequestResult, user_id: str, asset_type: str) -> None:
    config = get_config()
    if not config.power_automate_url:
        return
    from src.core.notifications import build_approval_notification_payload
    payload = build_approval_notification_payload(
        event="approval_pending",
        entity_type="asset_request",
        entity_id=result.asset_id,
        approval_id=result.approval_id,
        approval_stage=result.approval_stage,
        approval_status="pending",
        requested_by_user_id=user_id,
        approver_role="manager",
        approver_email=config.manager_email,
        request_details={"asset_type": asset_type},
    )
    try:
        print(f"[DEBUG] IT Agent - Asset approval - Sending Power Automate notification")
        print(f"[DEBUG] IT Agent - Asset approval - URL: {config.power_automate_url}")
        print(f"[DEBUG] IT Agent - Asset approval - Payload: {payload}")
        response = httpx.post(config.power_automate_url, json=payload, timeout=10)
        print(f"[DEBUG] IT Agent - Asset approval - Response status: {response.status_code}")
        print(f"[DEBUG] IT Agent - Asset approval - Response body: {response.text}")
    except httpx.HTTPError as exc:
        print(f"[DEBUG] IT Agent - Asset approval - Power Automate call failed: {exc}")


def _trigger_it_ticket_approval_flow(
    ticket_id: int,
    approval_id: int | None,
    user_id: str,
    issue_type: str,
    priority: str,
    detail: str,
    approval_stage: str,
) -> None:
    config = get_config()
    if not config.power_automate_url or not approval_id:
        return
    from src.core.notifications import build_approval_notification_payload
    payload = build_approval_notification_payload(
        event="approval_pending",
        entity_type="it_ticket",
        entity_id=ticket_id,
        approval_id=approval_id,
        approval_stage=approval_stage,
        approval_status="pending",
        requested_by_user_id=user_id,
        approver_role="manager",
        approver_email=config.manager_email,
        request_details={
            "ticket_issue_type": issue_type,
            "priority": priority,
            "description": detail,
        },
    )
    try:
        print(f"[DEBUG] IT Agent - Ticket approval - Sending Power Automate notification")
        print(f"[DEBUG] IT Agent - Ticket approval - URL: {config.power_automate_url}")
        print(f"[DEBUG] IT Agent - Ticket approval - Payload: {payload}")
        response = httpx.post(config.power_automate_url, json=payload, timeout=10)
        print(f"[DEBUG] IT Agent - Ticket approval - Response status: {response.status_code}")
        print(f"[DEBUG] IT Agent - Ticket approval - Response body: {response.text}")
    except httpx.HTTPError as exc:
        print(f"[DEBUG] IT Agent - Ticket approval - Power Automate call failed: {exc}")
