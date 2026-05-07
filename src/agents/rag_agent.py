import re
from dataclasses import dataclass

from src.agents.base import AgentResult, BaseAgent
from src.config import get_config
from src.core.memory import MemoryManager
from src.core.model_selector import call_model
from src.tools.vector_store import RAGStore, RetrievedDoc

rag_store = RAGStore(get_config().vector_db_path)
memory_manager = MemoryManager()

import logging
import os
from openai import OpenAI

RAG_PROMPT = (
    "SYSTEM:\n"
    "You are an internal enterprise assistant.\n"
    "Answer ONLY using the provided context.\n"
    "If information is unavailable in context, clearly say so.\n"
    "Do not hallucinate policies or approvals.\n\n"
    "CONTEXT:\n"
    "{context}\n\n"
    "USER QUERY:\n"
    "{query}"
)

TERM_ALIASES = {
    "expense": {"expense", "expenses", "charge", "charges", "cost", "costs"},
    "reimbursement": {"reimbursement", "reimbursements", "reimburse", "reimbursed", "claim", "claims", "claimed"},
    "claim": {"claim", "claims", "claimed", "reimburse", "reimbursement"},
    "claimed": {"claim", "claims", "claimed", "reimburse", "reimbursement"},
    "receipt": {"receipt", "receipts", "bill", "bills", "invoice", "invoices"},
    "receipts": {"receipt", "receipts", "bill", "bills", "invoice", "invoices"},
    "submit": {"submit", "submits", "submitted", "submission"},
    "submitted": {"submit", "submits", "submitted", "submission"},
    "eligible": {"eligible", "eligibility", "entitled", "covered"},
    "eligibility": {"eligible", "eligibility", "entitled", "covered"},
    "approval": {"approval", "approvals", "approve", "approved", "approver"},
}


@dataclass(frozen=True)
class QueryProfile:
    original: str
    normalized: str
    retrieval_query: str
    terms: set[str]
    required_terms: set[str]
    phrases: list[str]
    topic_terms: list[str]
    specific_topic: bool


class RAGAgent(BaseAgent):
    name = "rag"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "")
        role = state.get("role", "")
        model = state.get("model")
        intent = state.get("intent", "general")
        response = build_rag_response(
            query,
            role=role,
            intent=intent,
            k=6,
            model=model,
            user_id=state.get("user_id"),
            session_id=state.get("session_id"),
        )
        return AgentResult(response=response)


def ingest_documents(docs: list[RetrievedDoc]) -> None:
    rag_store.add_documents(docs)


def build_rag_response(
    query: str,
    role: str,
    intent: str = "general",
    k: int = 3,
    model: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> str:
    logging.info(f"[QUERY] {query}")
    logging.info(f"[INTENT] {intent}")
    
    profile = _build_query_profile(query, user_id, session_id)
    cached = rag_store.cache_get(profile.retrieval_query, role)
    if cached:
        return cached

    results = rag_store.query(
        profile.retrieval_query,
        k=max(k, 12),
        role=role,
        topic_terms=profile.topic_terms,
        rerank=True,
        rerank_k=18,
    )
    if not results:
        results = rag_store.query(
            profile.retrieval_query,
            k=max(k, 12),
            role=role,
            topic_terms=None,
            rerank=True,
            rerank_k=18,
        )
    if not results:
        return _general_knowledge_fallback(query, model)
    results = rag_store.expand_context(results, window=2)

    scored = []
    for doc in results:
        score = _score_retrieved_doc(doc, profile)
        if score > 0:
            scored.append((score, doc))

    if not scored:
        return _general_knowledge_fallback(query, model)

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score = scored[0][0]
    top_docs = _select_context_docs(scored, best_score)
    if profile.specific_topic and not _has_direct_evidence(top_docs, profile.required_terms, profile.phrases):
        return _general_knowledge_fallback(query, model)

    answer = _synthesize_answer(query, top_docs, profile.terms, profile.phrases, model=model)
    if "No relevant information found" not in answer:
        rag_store.cache_set(profile.retrieval_query, role, answer)
    elif model:
        return _general_knowledge_fallback(query, model)
    return answer

def _general_knowledge_fallback(query: str, model: str | None) -> str:
    if model:
        fallback_prompt = f"Please answer the following question to the best of your general knowledge:\n\nQuestion: {query}"
        model_response = call_model(model, fallback_prompt)
        if model_response:
            return f"- Found no local documents. From general knowledge:\n{model_response}"
    return "- No relevant information found in the provided context."


def _synthesize_answer(
    query: str,
    docs: list[RetrievedDoc],
    terms: set[str],
    phrases: list[str],
    model: str | None = None,
) -> str:
    summary_items = _summarize_docs(docs, terms, phrases)
    fallback_answer = (
        _format_policy_answer(query, summary_items)
        if summary_items
        else "- No relevant information found in the provided context."
    )
    
    context = _build_chunks(docs, terms, phrases)
    logging.info(f"[CHUNK COUNT] {len(docs)}")
    logging.info(f"[RETRIEVED CHUNKS]\n{context}")

    # Just return the context chunks. The central generator will handle Groq execution.
    return context if context else fallback_answer


def _answer_quality(answer: str) -> int:
    lowered = answer.lower()
    bullet_count = sum(1 for line in answer.splitlines() if line.strip().startswith("-"))
    detail_markers = (
        "scope",
        "eligible",
        "amount",
        "inr",
        "receipt",
        "submit",
        "deadline",
        "approval",
        "exception",
        "days",
        "month",
    )
    return bullet_count * 4 + sum(1 for marker in detail_markers if marker in lowered)


def _build_chunks(docs: list[RetrievedDoc], terms: set[str], phrases: list[str]) -> str:
    lines = []
    seen_excerpts = set()
    idx = 1
    for doc in docs[:8]:
        excerpt = _relevant_excerpt(doc.content, terms, phrases)
        if not excerpt or excerpt in seen_excerpts:
            continue
        seen_excerpts.add(excerpt)
        
        path = doc.metadata.get("path", "")
        section = doc.metadata.get("section", "")
        topic = doc.metadata.get("topic", "")
        subtopic = doc.metadata.get("subtopic", "")
        meta = ", ".join(part for part in (section, topic, subtopic) if part)
        source = f"source: {path}" if path else ""
        extras = ", ".join(part for part in (meta, source) if part)
        
        if extras:
            lines.append(f"[{idx}] {excerpt} ({extras})")
        else:
            lines.append(f"[{idx}] {excerpt}")
        idx += 1
    return "\n".join(lines)


def _normalize_model_answer(query: str, text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "- No relevant information found in the provided context."
    normalized = "\n".join(lines)
    normalized = _finalize_answer(query, normalized)
    if "\n" in normalized:
        if all(line.startswith("-") for line in normalized.splitlines()):
            return normalized
    return "\n".join(f"- {line.lstrip('-').strip()}" for line in normalized.splitlines() if line.strip())


def _format_policy_answer(query: str, items: list[str]) -> str:
    is_brief = _is_brief_query(query)
    cleaned_items = [_polish_item(item) for item in items]
    cleaned_items = [item for item in cleaned_items if item]
    if is_brief:
        cleaned_items = cleaned_items[:2]
    else:
        cleaned_items = cleaned_items[:6]
    if not cleaned_items:
        cleaned_items = ["No specific policy details were found in the retrieved documents."]
    return _finalize_answer(query, "\n".join(f"- {item}" for item in cleaned_items))


def _finalize_answer(query: str, text: str) -> str:
    qtype = _question_type(query)
    if qtype == "number":
        match = re.search(r"\b\d+(?:\.\d+)?\b", text)
        return match.group(0) if match else text
    if qtype == "person":
        match = re.search(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2}\b", text)
        return match.group(0) if match else text
    if qtype == "policy":
        return _ensure_bullets(text)
    return text


def _question_type(query: str) -> str:
    lowered = query.lower()
    if any(term in lowered for term in ("who", "name", "person", "manager", "approver")):
        return "person"
    if any(term in lowered for term in ("how many", "number", "count", "days")):
        return "number"
    if any(term in lowered for term in ("policy", "rules", "handbook", "leave", "benefit", "procedure", "process")):
        return "policy"
    return "other"


def _ensure_bullets(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "- No relevant information found in the provided context."
    if all(line.startswith("-") for line in lines):
        return "\n".join(lines)
    return "\n".join(f"- {line.lstrip('-').strip()}" for line in lines)


def _is_brief_query(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in ("brief", "short", "concise", "summary"))


def _polish_item(item: str) -> str:
    cleaned = " ".join(item.split())
    cleaned = cleaned.replace("\uf0b7", "-").replace("\u2022", "-")
    cleaned = cleaned.replace("\u2013", "-").replace("\u2014", "-")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    cleaned = cleaned.replace(" ina ", " in a ")
    cleaned = cleaned.replace("Tobe", "To be")
    cleaned = cleaned.replace("Manger", "Manager")
    cleaned = re.sub(r"^\d+\s*\|?\s*", "", cleaned)
    cleaned = re.sub(r"\s+\d+\.$", ".", cleaned)
    return cleaned.strip()


def _first_sentence(text: str) -> str:
    if not text:
        return ""
    for sep in (". ", ".\n"):
        if sep in text:
            return text.split(sep, 1)[0].strip() + "."
    return text.strip()


def _best_sentence(text: str, terms: set[str], phrases: list[str]) -> str:
    if not text:
        return ""
    sentences = text.replace("\n", " ").split(". ")
    scored = [
        (_score_doc(sentence, terms, phrases), sentence.strip())
        for sentence in sentences
        if sentence.strip()
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] > 0:
        sentence = scored[0][1]
        return sentence if sentence.endswith(".") else f"{sentence}."
    return _first_sentence(text)


def _query_terms(query: str) -> set[str]:
    stop = {
        "the",
        "is",
        "are",
        "a",
        "an",
        "of",
        "from",
        "explain",
        "tell",
        "me",
        "about",
        "to",
        "for",
        "and",
        "what",
        "how",
        "many",
        "policy",
        "policies",
        "procedure",
        "procedures",
        "process",
        "processes",
        "guideline",
        "guidelines",
        "please",
        "briefly",
        "brief",
        "short",
        "details",
        "company",
        "novigo",
    }
    terms = set(_tokenize(query))
    expanded: set[str] = set()
    for term in terms:
        if term in stop:
            continue
        expanded.add(term)
        if term.endswith("ies") and len(term) > 4:
            expanded.add(term[:-3] + "y")
        elif term.endswith("s") and len(term) > 3:
            expanded.add(term[:-1])
    return expanded


def _rewrite_query(query: str) -> str:
    lowered = query.lower().strip()
    normalized = re.sub(r"[_\-/]+", " ", lowered)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _augment_query_with_context(query: str, user_id: str | None, session_id: str | None) -> str:
    if not _needs_conversation_context(query):
        return query
    context_bits: list[str] = []
    if session_id:
        for message in reversed(memory_manager.get_context(session_id)[-3:]):
            previous_query = str(message.get("query", "")).strip()
            if previous_query:
                context_bits.append(previous_query)
    if user_id and not context_bits:
        recent = memory_manager.load_long_term(user_id, limit=3)
        context_bits.extend(recent)
    if not context_bits:
        return query
    context = " ".join(context_bits)
    return f"{query} {context}".strip()


def _score_doc(
    text: str,
    terms: set[str],
    phrases: list[str] | None = None,
    required_terms: set[str] | None = None,
) -> int:
    lowered = text.lower()
    tokens = set(_tokenize(lowered))
    required_terms = required_terms or set()
    missing_required = {term for term in required_terms if not _term_present(term, tokens, lowered)}
    if missing_required and len(required_terms) <= 3:
        return 0
    score = sum(2 for term in terms if _term_present(term, tokens, lowered))
    for phrase in phrases or []:
        if _phrase_present(phrase, lowered):
            score += 12
    if required_terms:
        matched = len(required_terms - missing_required)
        score += matched * 4
        if missing_required:
            score = max(0, score - len(missing_required) * 3)
    if phrases and not any(_phrase_present(phrase, lowered) for phrase in phrases):
        score = max(0, score - 4)
    return score


def _score_retrieved_doc(doc: RetrievedDoc, profile: QueryProfile) -> int:
    score = _score_doc(doc.content, profile.terms, profile.phrases, profile.required_terms)
    if score <= 0:
        return 0
    metadata_text = " ".join(
        str(doc.metadata.get(key, ""))
        for key in ("section", "topic", "subtopic", "path")
    ).lower()
    tokens = set(_tokenize(metadata_text))
    for phrase in profile.phrases:
        if _phrase_present(phrase, metadata_text):
            score += 10
    for term in profile.required_terms:
        if _term_present(term, tokens, metadata_text):
            score += 5
    if "leave" in profile.normalized and "leave" in metadata_text:
        score += 3
    return score


def _select_context_docs(scored: list[tuple[int, RetrievedDoc]], best_score: int) -> list[RetrievedDoc]:
    if not scored:
        return []
    best_path = str(scored[0][1].metadata.get("path", ""))
    if _is_dedicated_policy_source(best_path):
        same_source = [
            doc
            for score, doc in scored
            if doc.metadata.get("path") == best_path and score >= max(1, best_score - 25)
        ]
        if same_source:
            return same_source[:8]
    return [doc for score, doc in scored if score >= max(1, best_score - 20)][:8]


def _is_dedicated_policy_source(path: str) -> bool:
    lowered = path.lower()
    if not lowered:
        return False
    broad_sources = ("employee_handbook", "employee handbook")
    return lowered.endswith(".pdf") and not any(source in lowered for source in broad_sources)


def _summarize_docs(docs: list[RetrievedDoc], terms: set[str], phrases: list[str]) -> list[str]:
    policy_items = _extract_policy_items(docs, terms, phrases)
    if policy_items:
        return policy_items[:6]

    sentences: list[str] = []
    for doc in docs:
        excerpt = doc.content.replace("\n", " ")
        sentence = _best_sentence(excerpt, terms, phrases)
        if sentence:
            sentences.append(sentence)
        if len(sentences) >= 6:
            break
    cleaned = _clean_sentences(sentences)
    if not cleaned:
        return ["I found related HR documents, but no specific matching policy details."]
    return cleaned[:3]


def _extract_policy_items(docs: list[RetrievedDoc], terms: set[str], phrases: list[str]) -> list[str]:
    detail_items: list[tuple[int, int, str]] = []
    scope_items: list[tuple[int, int, str]] = []
    scored_items: list[tuple[int, int, int, str]] = []
    for doc_idx, doc in enumerate(docs):
        doc_score = _score_doc(doc.content, terms, phrases)
        if doc_score <= 0:
            continue
        in_policy_details = "policy details" in doc.content.lower()
        doc_topic_match = _doc_matches_topic(doc, terms, phrases)
        for unit_idx, unit in enumerate(_answer_units(doc.content)):
            unit_score = _score_doc(unit, terms, phrases)
            is_scope_unit = unit.lower().startswith("scope:") or (
                " eligible " in f" {unit.lower()} " and len(unit.split()) <= 35
            )
            if unit_score <= 0 and not (
                (is_scope_unit and doc_topic_match)
                or (in_policy_details and doc_topic_match and _looks_like_policy_detail(unit))
            ):
                continue
            if _is_boilerplate_unit(unit):
                continue
            if _is_overbroad_unit(unit, terms, phrases):
                continue
            if is_scope_unit and doc_topic_match:
                scope_items.append((doc_idx, unit_idx, unit))
            if in_policy_details and _looks_like_policy_detail(unit):
                detail_items.append((doc_idx, unit_idx, unit))
                continue
            score = unit_score + (6 if in_policy_details else 0) + max(0, 4 - unit_idx)
            scored_items.append((score, doc_idx, unit_idx, unit))

    if detail_items:
        ordered_scope = [unit for _, _, unit in sorted(scope_items)[:1]]
        ordered_details = [unit for _, _, unit in sorted(detail_items)]
        return _clean_sentences(ordered_scope + ordered_details)

    scored_items.sort(key=lambda item: (-item[0], item[1], item[2]))
    return _clean_sentences([item for _, _, _, item in scored_items])


def _answer_units(text: str) -> list[str]:
    normalized = text.replace("\n", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"\s+-\s+", "\n- ", normalized)
    units: list[str] = []
    for part in normalized.splitlines():
        stripped = part.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            cleaned = _strip_unit_boilerplate(stripped[2:].strip())
            if cleaned:
                units.append(cleaned)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        units.extend(unit for sentence in sentences if (unit := _strip_unit_boilerplate(sentence.strip())))
    return units


def _looks_like_policy_detail(text: str) -> bool:
    lowered = text.lower()
    detail_markers = (
        "employee",
        "employees",
        "amount",
        "inr",
        "receipt",
        "receipts",
        "submit",
        "claim",
        "charges",
        "eligible",
        "exception",
        "approved",
        "deadline",
        "month",
    )
    return any(marker in lowered for marker in detail_markers)


def _is_overbroad_unit(text: str, terms: set[str], phrases: list[str]) -> bool:
    lowered = text.lower()
    if "glossary" in lowered or "classification internal page" in lowered:
        return True
    words = lowered.split()
    if len(words) <= 55:
        return False
    direct_hits = sum(1 for term in terms if _term_present(term, set(words), lowered))
    phrase_hits = sum(1 for phrase in phrases if _phrase_present(phrase, lowered))
    return direct_hits + phrase_hits <= 2


def _is_boilerplate_unit(text: str) -> bool:
    lowered = text.lower()
    boilerplate = (
        "www.novigosolutions.com",
        "novigo solutions pvt. ltd",
        "classification | internal",
        "doc no",
        "doc version",
        "page no",
    )
    return len(lowered.split()) < 8 and any(marker in lowered for marker in boilerplate)


def _doc_matches_topic(doc: RetrievedDoc, terms: set[str], phrases: list[str]) -> bool:
    metadata_text = " ".join(
        str(doc.metadata.get(key, ""))
        for key in ("path", "section", "topic", "subtopic")
    ).lower()
    tokens = set(_tokenize(metadata_text))
    if phrases and any(_phrase_present(phrase, metadata_text) for phrase in phrases):
        return True
    strong_terms = {term for term in terms if term not in {"leave", "policy", "employee", "employees"}}
    return any(_term_present(term, tokens, metadata_text) for term in strong_terms)


def _strip_unit_boilerplate(text: str) -> str:
    cleaned = text.strip()
    lowered = cleaned.lower()
    cut_markers = (
        "www.novigosolutions.com",
        "classification | internal",
        "doc no",
        "doc version",
    )
    cut_positions = [lowered.find(marker) for marker in cut_markers if marker in lowered]
    cut_at = min((position for position in cut_positions if position > 0), default=-1)
    if cut_at > 0:
        cleaned = cleaned[:cut_at].strip()
    cleaned = re.sub(r"^policy details:\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -")


def _relevant_excerpt(text: str, terms: set[str], phrases: list[str]) -> str:
    normalized = text.replace("\n", " ")
    lowered = normalized.lower()
    positions = [lowered.find(phrase) for phrase in phrases if phrase in lowered]
    if not positions:
        positions = [lowered.find(term) for term in terms if term in lowered]
    match_at = min((pos for pos in positions if pos >= 0), default=0)
    start = max(0, match_at - 120)
    end = min(len(normalized), match_at + 420)
    excerpt = normalized[start:end].strip()
    if start > 0:
        excerpt = f"... {excerpt}"
    if end < len(normalized):
        excerpt = f"{excerpt} ..."
    return excerpt


def _expand_query(query: str) -> str:
    expansions = []
    if "expense" in query or "reimbursement" in query:
        expansions.extend(["expenses", "reimburse", "claim", "receipts", "bills", "telephone", "internet", "charges", "amount"])
    if "onsite" in query or "on site" in query or "on-site" in query:
        expansions.extend(["on site", "on-site", "onsite", "client site", "office site", "work location"])
    if "sick leave" in query:
        expansions.extend(["medical leave", "illness leave", "sl"])
    if "work from home" in query:
        expansions.extend(["remote work", "wfh", "telework", "home working"])
    if "maternity" in query or "maternal" in query:
        expansions.extend(["maternity leave", "maternal leave"])
    if "policy" in query:
        expansions.extend(["guidelines", "rules", "handbook"])
    if "procedure" in query or "process" in query:
        expansions.extend(["steps", "process", "workflow", "guidelines"])
    return " ".join([query] + expansions)


def _topic_terms(query: str) -> list[str]:
    if "expense" in query or "reimbursement" in query:
        return ["expense", "expenses", "reimbursement", "reimburse", "claim", "receipts"]
    if "sick leave" in query:
        return ["sick", "leave", "medical"]
    if "annual leave" in query or "vacation" in query:
        return ["annual", "vacation", "leave", "pto"]
    if "bereavement" in query:
        return ["bereavement", "grief", "leave"]
    if "casual leave" in query:
        return ["casual", "leave"]
    if "unpaid leave" in query:
        return ["unpaid", "leave", "lwp"]
    if "parental leave" in query or "maternity" in query or "paternity" in query:
        return ["parental", "maternity", "paternity", "leave"]
    if "work from home" in query or "wfh" in query or "remote work" in query or "hybrid work" in query:
        return ["work", "home", "wfh", "remote", "hybrid"]
    if "onsite" in query or "on site" in query or "on-site" in query:
        return ["onsite", "on site", "office", "site", "work location"]
    terms = _query_terms(query)
    ranked = sorted(terms, key=lambda term: (-len(term), term))
    return ranked[:3]


def _is_specific_topic(query: str) -> bool:
    specific_terms = (
        "sick leave",
        "annual leave",
        "vacation",
        "casual leave",
        "unpaid leave",
        "bereavement",
        "parental leave",
        "maternity",
        "paternity",
        "work from home",
        "wfh",
        "remote work",
        "hybrid work",
        "onsite",
        "on site",
        "on-site",
        "client site",
    )
    return any(term in query for term in specific_terms)


def _intent_phrases(query: str) -> list[str]:
    phrases: list[str] = []
    if "expense" in query or "reimbursement" in query:
        phrases.extend(["expense reimbursement", "reimbursement policy", "policy details"])
    if "sick leave" in query:
        phrases.extend(["sick leave", "medical leave", "sl"])
    if "work from home" in query or "wfh" in query:
        phrases.extend(["work from home", "working from home", "wfh", "remote work", "hybrid work"])
    if "maternity" in query:
        phrases.extend(["maternity leave", "maternity"])
    if "paternity" in query:
        phrases.extend(["paternity leave", "paternity"])
    if "onsite" in query or "on site" in query or "on-site" in query:
        phrases.extend(["onsite", "on site", "on-site", "client site"])
    return phrases


def _build_query_profile(query: str, user_id: str | None, session_id: str | None) -> QueryProfile:
    normalized = _rewrite_query(query)
    contextual = _augment_query_with_context(normalized, user_id, session_id)
    retrieval_query = _expand_query(contextual)
    terms = _query_terms(contextual)
    original_terms = _query_terms(normalized)
    required_terms = _required_terms(normalized, original_terms)
    phrases = _intent_phrases(contextual)
    return QueryProfile(
        original=query,
        normalized=normalized,
        retrieval_query=retrieval_query,
        terms=terms,
        required_terms=required_terms,
        phrases=phrases,
        topic_terms=_topic_terms(contextual),
        specific_topic=_is_specific_topic(contextual) or bool(required_terms),
    )


def _required_terms(query: str, terms: set[str]) -> set[str]:
    required = set()
    important = {
        "onsite",
        "paternity",
        "maternity",
        "bereavement",
        "casual",
        "sick",
        "annual",
        "unpaid",
        "reimbursement",
        "expense",
        "whistleblowing",
        "attendance",
    }
    for term in terms:
        if term in important or len(term) >= 7:
            required.add(term)
    if "on site" in query or "on-site" in query:
        required.add("site")
    return required


def _has_direct_evidence(docs: list[RetrievedDoc], required_terms: set[str], phrases: list[str]) -> bool:
    if not required_terms and not phrases:
        return True
    for doc in docs:
        lowered = doc.content.lower()
        tokens = set(_tokenize(lowered))
        if phrases and any(_phrase_present(phrase, lowered) for phrase in phrases):
            return True
        if required_terms and all(_term_present(term, tokens, lowered) for term in required_terms):
            return True
    return False


def _needs_conversation_context(query: str) -> bool:
    tokens = _tokenize(query)
    if len(tokens) <= 3 and any(term in tokens for term in ("it", "this", "that", "same", "above")):
        return True
    vague = {
        "procedure",
        "procedures",
        "process",
        "policy",
        "details",
        "eligibility",
        "eligible",
        "amount",
        "limit",
        "deadline",
        "submit",
        "claim",
        "claimed",
        "receipt",
        "receipts",
        "exceptions",
        "scope",
    }
    question_words = {"what", "how", "when", "where", "who", "why", "is", "are", "do", "does", "the", "my"}
    content_tokens = [token for token in tokens if token not in question_words]
    return len([token for token in content_tokens if token not in vague]) <= 1 and bool(set(tokens) & vague)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _term_present(term: str, tokens: set[str], lowered: str) -> bool:
    if term == "onsite":
        return "onsite" in tokens or bool(re.search(r"\bon\s*[- ]\s*site\b", lowered))
    for variant in _term_variants(term):
        if variant in tokens or bool(re.search(rf"\b{re.escape(variant)}\b", lowered)):
            return True
    return False


def _term_variants(term: str) -> set[str]:
    variants = {term}
    variants.update(TERM_ALIASES.get(term, set()))
    if term.endswith("y") and len(term) > 3:
        variants.add(term[:-1] + "ies")
    if term.endswith("s") and len(term) > 3:
        variants.add(term[:-1])
    else:
        variants.add(term + "s")
    return variants


def _phrase_present(phrase: str, lowered: str) -> bool:
    if phrase in {"on site", "on-site"}:
        return bool(re.search(r"\bon\s*[- ]\s*site\b", lowered))
    pattern = re.escape(phrase).replace(r"\ ", r"\s+")
    return bool(re.search(rf"\b{pattern}\b", lowered))


def _clean_sentences(sentences: list[str]) -> list[str]:
    seen = set()
    cleaned: list[str] = []
    for sentence in sentences:
        normalized = " ".join(sentence.lower().split())
        if len(normalized.split()) < 4:
            continue
        if _is_noisy_sentence(normalized):
            continue
        if normalized in seen or _is_near_duplicate(normalized, seen):
            continue
        seen.add(normalized)
        cleaned.append(sentence.strip())
    return cleaned


def _is_noisy_sentence(sentence: str) -> bool:
    noisy_markers = ("eess", "suee", "scss", "secs", "cucs", "aaaa")
    if any(marker in sentence for marker in noisy_markers):
        return True
    if "warning issued" in sentence or "regards, xxxx" in sentence:
        return True
    words = sentence.split()
    if len(words) > 35:
        short_or_garbled = sum(1 for word in words if len(word) > 18 or not any(ch in "aeiou" for ch in word))
        if short_or_garbled / len(words) > 0.25:
            return True
    return False


def _is_near_duplicate(sentence: str, seen: set[str]) -> bool:
    words = set(sentence.split())
    if not words:
        return True
    for previous in seen:
        previous_words = set(previous.split())
        if not previous_words:
            continue
        overlap = len(words & previous_words) / min(len(words), len(previous_words))
        if overlap >= 0.82:
            return True
    return False
