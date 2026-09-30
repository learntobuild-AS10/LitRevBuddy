from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader

from models.story import PaperSource, ParsedPaper


MAX_PAGES = 100
MAX_EXTRACTED_CHARS = 220_000
MIN_USEFUL_CHARS = 800

SECTION_PATTERNS = {
    "abstract": r"abstract",
    "introduction": r"(?:\d+(?:\.\d+)*\s+)?introduction",
    "method": r"(?:\d+(?:\.\d+)*\s+)?(?:method|methods|methodology|approach|model|architecture)",
    "experiments": r"(?:\d+(?:\.\d+)*\s+)?(?:experiments?|experimental setup|evaluation)",
    "results": r"(?:\d+(?:\.\d+)*\s+)?(?:results?|findings)",
    "discussion": r"(?:\d+(?:\.\d+)*\s+)?discussion",
    "limitations": r"(?:\d+(?:\.\d+)*\s+)?(?:limitations?|limitations and future work)",
    "conclusion": r"(?:\d+(?:\.\d+)*\s+)?(?:conclusion|conclusions|concluding remarks)",
}


class PDFParseError(RuntimeError):
    pass


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _match_heading(line: str) -> str | None:
    candidate = " ".join(line.strip().split())
    if not candidate or len(candidate) > 90:
        return None
    lower = candidate.lower().rstrip(":.")
    for section, pattern in SECTION_PATTERNS.items():
        if re.fullmatch(pattern, lower, flags=re.I):
            return section
    return None


def extract_sections(text: str) -> dict[str, str]:
    lines = text.splitlines()
    hits: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        section = _match_heading(line)
        if section:
            hits.append((index, section))

    sections: dict[str, str] = {}
    for hit_index, (line_index, section) in enumerate(hits):
        if section in sections:
            continue
        end_index = hits[hit_index + 1][0] if hit_index + 1 < len(hits) else len(lines)
        body = _clean_text("\n".join(lines[line_index + 1 : end_index]))
        if len(body) >= 40:
            sections[section] = body
    return sections


def _guess_title(first_page_text: str) -> str:
    lines = [" ".join(line.split()) for line in first_page_text.splitlines()]
    lines = [line for line in lines if 8 <= len(line) <= 220]
    blocked = re.compile(r"^(abstract|introduction|arxiv|proceedings|copyright)\b", re.I)
    candidates = [line for line in lines[:15] if not blocked.search(line)]
    if not candidates:
        return "Uploaded paper"
    return candidates[0]


def parse_pdf_bytes(data: bytes, source: PaperSource) -> ParsedPaper:
    if not data or not data.startswith(b"%PDF"):
        raise PDFParseError("The uploaded or fetched file is not a valid PDF.")

    try:
        reader = PdfReader(BytesIO(data), strict=False)
    except Exception as exc:
        raise PDFParseError("The PDF could not be opened.") from exc

    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")
        except Exception as exc:
            raise PDFParseError("The PDF is encrypted and could not be opened without a password.") from exc
        if not decrypted:
            raise PDFParseError("The PDF is password-protected. Upload an unlocked copy.")

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise PDFParseError("The PDF page structure could not be read.") from exc

    if page_count == 0:
        raise PDFParseError("The PDF contains no readable pages.")

    notes: list[str] = []
    if page_count > MAX_PAGES:
        notes.append(f"Only the first {MAX_PAGES} pages were parsed.")

    page_texts = []
    total_chars = 0
    for page_index in range(min(page_count, MAX_PAGES)):
        page_number = page_index + 1
        try:
            page = reader.pages[page_index]
            text = page.extract_text() or ""
        except Exception:
            notes.append(f"Page {page_number} could not be extracted.")
            continue
        text = _clean_text(text)
        if not text:
            continue
        remaining = MAX_EXTRACTED_CHARS - total_chars
        if remaining <= 0:
            notes.append("Extracted text was truncated to keep generation bounded.")
            break
        text = text[:remaining]
        page_texts.append(text)
        total_chars += len(text)

    full_text = _clean_text("\n\n".join(page_texts))
    if len(full_text) < MIN_USEFUL_CHARS:
        raise PDFParseError("Very little text could be extracted. This PDF may be scanned, image-only, or malformed.")

    if not source.title or source.title in {"External paper", "Uploaded paper"}:
        source.title = _guess_title(page_texts[0] if page_texts else full_text)

    sections = extract_sections(full_text)

    if source.abstract:
        sections.setdefault("abstract", source.abstract)
    elif "abstract" in sections:
        source.abstract = sections["abstract"][:6000]

    if len(sections) < 2:
        notes.append("Section headings were not reliably detected; generation will use extracted full text with lower structural confidence.")

    return ParsedPaper(
        source=source,
        sections=sections,
        full_text=full_text,
        source_quality="full_paper",
        extraction_notes=notes,
    )


def parsed_from_abstract(source: PaperSource) -> ParsedPaper:
    abstract = _clean_text(source.abstract)
    if len(abstract) < 40:
        raise PDFParseError("No usable abstract is available for this paper.")
    return ParsedPaper(
        source=source,
        sections={"abstract": abstract},
        full_text=abstract,
        source_quality="abstract",
        extraction_notes=["Only title/metadata and abstract were available."],
    )
