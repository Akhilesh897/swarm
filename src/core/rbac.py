ROLE_EMPLOYEE = "employee"
ROLE_MANAGER = "manager"
ROLE_IT_LEAD = "it_lead"
ROLE_FINANCE = "finance"
ROLE_ADMIN = "admin"

INTENT_HR = "hr"
INTENT_IT = "it"
INTENT_FINANCE = "finance"
INTENT_GENERAL = "general"

ROLE_PERMISSIONS = {
    INTENT_HR: {ROLE_EMPLOYEE, ROLE_MANAGER, ROLE_ADMIN},
    INTENT_IT: {ROLE_EMPLOYEE, ROLE_MANAGER, ROLE_IT_LEAD, ROLE_ADMIN},
    INTENT_FINANCE: {ROLE_EMPLOYEE, ROLE_MANAGER, ROLE_FINANCE, ROLE_ADMIN},
    INTENT_GENERAL: {ROLE_EMPLOYEE, ROLE_MANAGER, ROLE_IT_LEAD, ROLE_FINANCE, ROLE_ADMIN},
}

ROLE_INHERITANCE = {
    ROLE_MANAGER: {ROLE_EMPLOYEE},
    ROLE_IT_LEAD: {ROLE_EMPLOYEE},
    ROLE_ADMIN: {ROLE_EMPLOYEE, ROLE_MANAGER, ROLE_IT_LEAD, ROLE_FINANCE},
}


def _expanded_roles(role: str) -> set[str]:
    expanded = {role}
    stack = [role]
    while stack:
        current = stack.pop()
        for inherited in ROLE_INHERITANCE.get(current, set()):
            if inherited not in expanded:
                expanded.add(inherited)
                stack.append(inherited)
    return expanded


def check_access(role: str, intent: str) -> bool:
    if role == "it":
        role = ROLE_IT_LEAD
    allowed = ROLE_PERMISSIONS.get(intent, set())
    return bool(_expanded_roles(role) & allowed)
