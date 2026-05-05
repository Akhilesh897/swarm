from pathlib import Path
import re

from pypdf import PdfReader

from src.agents.rag_agent import ingest_documents
from src.tools.vector_store import RetrievedDoc

DEFAULT_CHUNK_SIZE = 420
DEFAULT_CHUNK_OVERLAP = 80
MAX_AUTO_INGEST_BYTES = 64 * 1024 * 1024
MIN_CHUNK_CHARS = 80


def ingest_folder(path: str, role: str = "general", chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> int:
    base = Path(path)
    docs: list[RetrievedDoc] = []
    for file_path in base.rglob("*"):
        if file_path.suffix.lower() not in {".txt", ".md", ".pdf"}:
            continue
        if file_path.stat().st_size > MAX_AUTO_INGEST_BYTES:
            continue
        content = _read_content(file_path)
        mtime = int(file_path.stat().st_mtime)
        for idx, chunk in enumerate(_chunk_text(content, chunk_size, chunk_overlap)):
            if _is_low_value_chunk(chunk):
                continue
            section, topic = _infer_chunk_section_topic(file_path, chunk)
            subtopic = _infer_subtopic(chunk)
            doc_id = f"{file_path}:{mtime}:{idx}"
            docs.append(
                RetrievedDoc(
                    content=chunk,
                    metadata={
                        "path": str(file_path),
                        "role": role,
                        "type": role,
                        "section": section,
                        "topic": topic,
                        "subtopic": subtopic,
                        "chunk": idx,
                        "doc_id": doc_id,
                    },
                )
            )

    ingest_documents(docs)
    return len(docs)


def _read_content(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return _normalize_text("\n".join(page.extract_text() or "" for page in reader.pages))
    return _normalize_text(path.read_text(encoding="utf-8", errors="ignore"))


def _infer_section_topic(path: Path, content: str) -> tuple[str, str]:
    section = ""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
        else:
            section = stripped
        break
    if not section:
        section = path.stem.replace("_", " ").replace("-", " ").strip()
    topic = _slugify(section)
    return section, topic


def _infer_chunk_section_topic(path: Path, chunk: str) -> tuple[str, str]:
    lowered = chunk.lower()
    topic_markers = [
        ("on-site", "onsite"),
        ("on site", "onsite"),
        ("onsite", "onsite"),
        ("client site", "onsite"),
        ("work location", "onsite"),
        ("work from home", "work from home"),
        ("working from home", "work from home"),
        ("wfh", "work from home"),
        ("remote work", "work from home"),
        ("hybrid work", "work from home"),
        ("maternity leave", "maternity leave"),
        ("paternity leave", "paternity leave"),
        ("bereavement leave", "bereavement leave"),
        ("casual leave", "casual leave"),
        ("sick leave", "sick leave"),
        ("expense reimbursement", "expense reimbursement"),
        ("code of conduct", "code of conduct"),
    ]
    for marker, section in topic_markers:
        if _contains_marker(lowered, marker):
            return section.title(), _slugify(section)
    return _infer_section_topic(path, chunk)


def _slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return "_".join(part for part in cleaned.split() if part)


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not text:
        return []

    sections = _split_sections(text)
    chunks: list[str] = []
    for section in sections:
        chunks.extend(_chunk_section(section, chunk_size, chunk_overlap))
    return [chunk for chunk in chunks if chunk and not _is_low_value_chunk(chunk)]


def _split_sections(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines()]
    sections: list[str] = []
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer and buffer[-1] != "":
                buffer.append("")
            continue
        if _is_heading(stripped):
            if buffer:
                sections.append("\n".join(buffer).strip())
                buffer = []
            buffer.append(stripped)
            continue
        buffer.append(stripped)
    if buffer:
        sections.append("\n".join(buffer).strip())
    return sections


def _chunk_section(section: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    tokens = _to_tokens(section)
    if not tokens:
        return []
    size = max(300, min(chunk_size, 520))
    overlap = max(50, min(chunk_overlap, size - 1))

    sentences = _split_sentences(section)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_tokens = _to_tokens(sentence)
        if not sentence_tokens:
            continue
        if current_len + len(sentence_tokens) > size and current:
            chunks.append(" ".join(current).strip())
            current = _apply_overlap(current, overlap)
            current_len = len(_to_tokens(" ".join(current)))
        current.append(sentence.strip())
        current_len += len(sentence_tokens)

    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def _apply_overlap(sentences: list[str], overlap: int) -> list[str]:
    if not sentences:
        return []
    tokens: list[str] = []
    for sentence in reversed(sentences):
        tokens = _to_tokens(sentence) + tokens
        if len(tokens) >= overlap:
            break
    if not tokens:
        return []
    return [" ".join(tokens)]


def _split_sentences(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_bullet(stripped):
            lines.append(stripped)
        else:
            parts = re.split(r"(?<=[.!?])\s+", stripped)
            lines.extend(part for part in parts if part)
    return lines


def _is_heading(line: str) -> bool:
    if line.startswith("#"):
        return True
    if line.isupper() and len(line.split()) <= 8:
        return True
    if line.endswith(":") and len(line.split()) <= 10:
        return True
    return False


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^(\d+\.|[-*•])\s+", line))


def _to_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text)


def _infer_subtopic(chunk: str) -> str:
    lowered = chunk.lower()
    markers = [
        ("on-site", "onsite"),
        ("on site", "onsite"),
        ("onsite", "onsite"),
        ("client site", "onsite"),
        ("sick leave", "sick_leave"),
        ("maternity", "maternity_leave"),
        ("paternity", "paternity_leave"),
        ("bereavement", "bereavement_leave"),
        ("casual leave", "casual_leave"),
        ("unpaid", "unpaid_leave"),
        ("work from home", "work_from_home"),
        ("wfh", "work_from_home"),
        ("reimbursement", "reimbursement"),
        ("expense", "expense"),
        ("code of conduct", "code_of_conduct"),
    ]
    for marker, subtopic in markers:
        if _contains_marker(lowered, marker):
            return subtopic
    return ""


def _is_low_value_chunk(chunk: str) -> bool:
    normalized = " ".join(chunk.split())
    if len(normalized) < MIN_CHUNK_CHARS:
        return True
    lowered = normalized.lower()
    boilerplate = (
        "classification | internal",
        "page no",
        "doc no",
        "doc version",
    )
    if sum(1 for marker in boilerplate if marker in lowered) >= 2 and len(normalized) < 260:
        return True
    alpha_chars = sum(1 for char in normalized if char.isalpha())
    return alpha_chars < max(30, len(normalized) * 0.45)


def _contains_marker(text: str, marker: str) -> bool:
    if marker in {"on site", "on-site"}:
        return bool(re.search(r"\bon\s*[- ]\s*site\b", text))
    pattern = re.escape(marker).replace(r"\ ", r"\s+")
    return bool(re.search(rf"\b{pattern}\b", text))


def _normalize_text(text: str) -> str:
    replacements = {
        "\uf0b7": "-",
        "\u2022": "-",
        "\u00a0": " ",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
