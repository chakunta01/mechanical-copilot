"""Text chunking for engineering documents.

Structure-aware: splits on headings first, then packs sections into
target-size chunks with overlap. Each chunk carries its nearest preceding
heading as section metadata, which becomes part of the citation trail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_heading_re = re.compile(r"^(#{1,6}\s+.+|\d+(\.\d+)*\s+\S.*|[A-Z][A-Z \-/&]{4,})\s*$")


@dataclass
class Chunk:
    ordinal: int
    text: str
    section: str
    meta: dict


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) pairs; text before the first heading uses '' as heading."""
    sections: list[tuple[str, str]] = []
    current_heading = ""
    buf: list[str] = []
    for line in text.splitlines():
        if _heading_re.match(line.strip()) and len(line.strip()) < 120:
            if buf:
                sections.append((current_heading, "\n".join(buf).strip()))
                buf = []
            current_heading = line.strip().lstrip("# ").strip()
        else:
            buf.append(line)
    if buf:
        sections.append((current_heading, "\n".join(buf).strip()))
    return sections


def chunk_text(
    text: str,
    *,
    target_chars: int = 1200,
    max_chars: int = 1800,
    overlap_chars: int = 150,
) -> list[Chunk]:
    """Chunk `text` by section, packing paragraphs up to target_chars with overlap."""
    text = text.strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    ordinal = 0

    for heading, body in _split_sections(text):
        if not body:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        current: list[str] = []
        size = 0

        def flush(cur: list[str], heading: str) -> None:
            nonlocal ordinal
            chunk_body = "\n\n".join(cur).strip()
            if not chunk_body:
                return
            prefix = f"{heading}\n" if heading else ""
            chunks.append(
                Chunk(
                    ordinal=ordinal,
                    text=f"{prefix}{chunk_body}",
                    section=heading,
                    meta={"section": heading},
                )
            )
            ordinal += 1

        for para in paragraphs:
            # Hard-split a pathologically long paragraph.
            while len(para) > max_chars:
                head, para = para[:max_chars], para[max_chars - overlap_chars :]
                current.append(head)
                flush(current, heading)
                current = []
                size = 0
            if size + len(para) > target_chars and current:
                flush(current, heading)
                tail = current[-1][-overlap_chars:] if overlap_chars else ""
                current = [tail] if tail else []
                size = len(current[0]) if current else 0
            current.append(para)
            size += len(para)
        flush(current, heading)

    return chunks


def extract_text_from_pdf(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_docx(data: bytes) -> str:
    from io import BytesIO

    import docx  # python-docx

    d = docx.Document(BytesIO(data))
    lines = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(lines)
