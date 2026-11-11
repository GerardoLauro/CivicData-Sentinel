"""Bounded document capture. Text is evidence, never executable instructions."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import datetime, timezone
from html.parser import HTMLParser

from pydantic import Field, model_validator

from ..config import ContractModel
from ..ingestion import _get_bytes


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "tr", "li", "h1", "h2"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract(raw: bytes, format: str) -> list[str]:
    if not raw or len(raw) > 8_000_000:
        raise ValueError("Document must contain 1..8,000,000 bytes")
    if format == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF extraction requires pip install 'civicdata-sentinel[contracts]'") from exc
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception as exc:
            raise ValueError("Unreadable PDF document") from exc
        if reader.is_encrypted or len(reader.pages) > 200:
            raise ValueError("Encrypted PDFs and documents over 200 pages are unsupported")
        pages = [page.extract_text() or "" for page in reader.pages]
    elif format in {"txt", "html", "json"}:
        text = raw.decode("utf-8-sig")
        if format == "html":
            parser = VisibleHTML()
            parser.feed(text)
            text = "".join(parser.parts)
        if format == "json":
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        pages = [text]
    else:
        raise ValueError("Supported document formats: txt, html, pdf, json")
    if sum(map(len, pages)) > 500_000:
        raise ValueError("Extracted text exceeds 500,000 characters")
    return pages


class Document(ContractModel):
    id: str
    origin: str
    format: str
    captured_at: str
    published_at: str | None = None
    raw_sha256: str
    raw_base64: str
    pages: list[str] = Field(max_length=200)

    @model_validator(mode="after")
    def intact(self):
        raw = base64.b64decode(self.raw_base64, validate=True)
        if sha(raw) != self.raw_sha256 or self.id != "doc-" + self.raw_sha256[:16]:
            raise ValueError("Document digest does not match its content")
        if self.pages != extract(raw, self.format):
            raise ValueError("Document extracted text does not match retained original")
        if self.published_at:
            datetime.fromisoformat(self.published_at)
        return self


def document(raw, *, origin, format, published_at=None):
    digest = sha(raw)
    return Document(
        id="doc-" + digest[:16],
        origin=origin,
        format=format,
        captured_at=utcnow(),
        published_at=published_at,
        raw_sha256=digest,
        raw_base64=base64.b64encode(raw).decode("ascii"),
        pages=extract(raw, format),
    )


def download_document(url, format, *, published_at=None):
    # Same bounded HTTPS transport as ingestion, with HTML explicitly enabled only here.
    return document(_get_bytes(url, allow_html=True), origin=url, format=format, published_at=published_at)
