import re


def is_question(query: str) -> bool:
    text = query.lower().strip()
    if "?" in text:
        if _has_action_terms(text):
            return False
        return True
    question_starters = (
        "what",
        "how",
        "when",
        "where",
        "who",
        "why",
        "which",
        "can",
        "could",
        "should",
        "may",
        "do",
        "does",
        "is",
        "are",
        "am",
        "will",
        "would",
        "tell me",
        "explain",
        "clarify",
    )
    if text.startswith(question_starters):
        return not _has_action_terms(text)
    return False


def _has_action_terms(text: str) -> bool:
    action_patterns = [
        r"\bapply\b",
        r"\brequest\b",
        r"\bcreate\b",
        r"\bsubmit\b",
        r"\braise\b",
        r"\bassign\b",
        r"\bresolve\b",
        r"\bapprove\b",
        r"\breject\b",
        r"\bbook\b",
        r"\bschedule\b",
        r"\border\b",
        r"\bissue\b",
        r"\blog\b",
        r"\bcancel\b",
        r"\bwithdraw\b",
        r"\bresubmit\b",
    ]
    return any(re.search(pattern, text) for pattern in action_patterns)

def classify_intent(query: str) -> str:
    """
    Returns one of:
    - 'policy'
    - 'action'
    - 'status'
    - 'other'
    """
    text = query.lower().strip()

    policy_patterns = [
        r"\bhow many\b",
        r"\bpolicy\b",
        r"\brules\b",
        r"\beligibility\b",
        r"\bentitled\b",
        r"\bentitlement\b",
        r"\ballowed\b",
        r"\bquota\b",
        r"\bthreshold\b",
        r"\blimits?\b",
        r"\bcoverage\b",
        r"\bamount\b",
        r"\bclaim(ed|s)?\b",
        r"\breceipts?\b",
        r"\bdeadline\b",
        r"\bwhen\b.*\bsubmit\b",
        r"\bsubmit\b.*\breceipts?\b",
        r"\breimbursement policy\b",
        r"\bapprov(al|als) process\b",
        r"\bguidelines\b",
        r"\bhandbook\b",
        r"\bcompliance\b",
    ]
    status_patterns = [
        r"\bstatus\b",
        r"\bcheck\b",
        r"\btrack\b",
        r"\bprogress\b",
        r"\bhistory\b",
        r"\bbalance\b",
        r"\bremaining\b",
        r"\bpending\b",
        r"\bapproval\s*status\b",
        r"\bticket\s*(id|number)\b",
        r"\brequest\s*(id|number)\b",
    ]
    action_patterns = [
        r"\bapply\b",
        r"\brequest\b",
        r"\bcreate\b",
        r"\bsubmit\b",
        r"\braise\b",
        r"\bassign\b",
        r"\bresolve\b",
        r"\bapprove\b",
        r"\breject\b",
        r"\bbook\b",
        r"\bschedule\b",
        r"\border\b",
        r"\bissue\b",
        r"\blog\b",
        r"\bcancel\b",
        r"\bwithdraw\b",
        r"\bresubmit\b",
    ]

    if any(re.search(pattern, text) for pattern in policy_patterns):
        return "policy"
    if any(re.search(pattern, text) for pattern in status_patterns):
        return "status"
    if any(re.search(pattern, text) for pattern in action_patterns):
        return "action"
    return "other"
