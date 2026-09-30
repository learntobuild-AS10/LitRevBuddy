from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from models.story import PaperSource


MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
USER_AGENT = "LitRevBuddy/1.0 (+https://litrevbuddy.streamlit.app/)"


class FetchError(RuntimeError):
    pass


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        data = {k.lower(): v for k, v in attrs if k and v is not None}
        key = data.get("name") or data.get("property")
        value = data.get("content")
        if key and value:
            self.meta.setdefault(key.lower(), []).append(value.strip())


def normalize_user_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise FetchError("Enter a paper URL, arXiv link, OpenReview link, DOI, or direct PDF URL.")

    if re.match(r"^10\.\d{4,9}/\S+$", value, flags=re.I):
        return f"https://doi.org/{value}"

    if not re.match(r"^https?://", value, flags=re.I):
        value = "https://" + value
    return value


def resolve_pdf_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    path = parsed.path

    if path.lower().endswith(".pdf"):
        return url

    if host in {"arxiv.org", "www.arxiv.org"}:
        match = re.search(r"/(?:abs|pdf)/([^?#]+)", path)
        if match:
            paper_id = match.group(1).removesuffix(".pdf")
            return f"https://arxiv.org/pdf/{paper_id}.pdf"

    if host in {"openreview.net", "www.openreview.net"}:
        query = parsed.query
        match = re.search(r"(?:^|&)id=([^&]+)", query)
        if match:
            return f"https://openreview.net/pdf?id={match.group(1)}"

    return ""


def _assert_public_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FetchError("Only public http(s) URLs are supported.")

    host = parsed.hostname
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise FetchError("Local or private network URLs are not allowed.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve host: {host}") from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
            raise FetchError("Private, local, or reserved network addresses are not allowed.")


def _request_with_safe_redirects(url: str, *, stream: bool, timeout=(5, 25), max_redirects=5):
    session = requests.Session()
    current = url
    for _ in range(max_redirects + 1):
        _assert_public_host(current)
        response = session.get(
            current,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8"},
            timeout=timeout,
            stream=stream,
            allow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise FetchError("The paper URL redirected without a destination.")
            current = urljoin(current, location)
            continue
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            response.close()
            raise FetchError(f"Paper request failed with HTTP {getattr(response, 'status_code', 'error')}.") from exc
        return response
    raise FetchError("Too many redirects while fetching the paper.")


def fetch_pdf_bytes(url: str, *, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    response = _request_with_safe_redirects(url, stream=True)
    try:
        content_type = (response.headers.get("Content-Type") or "").lower()
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    raise FetchError(f"PDF exceeds the {max_bytes // (1024 * 1024)} MB limit.")
            except ValueError:
                pass

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise FetchError(f"PDF exceeds the {max_bytes // (1024 * 1024)} MB limit.")
            chunks.append(chunk)

        data = b"".join(chunks)
        if not data.startswith(b"%PDF") and "pdf" not in content_type:
            raise FetchError("The resolved URL did not return a PDF.")
        return data
    finally:
        response.close()


def fetch_page_metadata(url: str) -> PaperSource:
    normalized = normalize_user_url(url)
    direct_pdf = resolve_pdf_url(normalized)
    if direct_pdf:
        return PaperSource(
            paper_id=normalized,
            title="External paper",
            paper_url=normalized,
            pdf_url=direct_pdf,
            source_kind="url",
        )

    response = _request_with_safe_redirects(normalized, stream=True)
    try:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "application/pdf" in content_type:
            return PaperSource(
                paper_id=response.url,
                title="External paper",
                paper_url=response.url,
                pdf_url=response.url,
                source_kind="url",
            )

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=32 * 1024):
            total += len(chunk)
            if total > MAX_HTML_BYTES:
                break
            chunks.append(chunk)
        html = b"".join(chunks).decode(response.encoding or "utf-8", errors="ignore")
        final_url = response.url
    finally:
        response.close()

    parser = _MetaParser()
    parser.feed(html)
    meta = parser.meta

    def first(*names: str) -> str:
        for name in names:
            values = meta.get(name.lower(), [])
            if values:
                return values[0]
        return ""

    title = first("citation_title", "dc.title", "og:title") or urlparse(final_url).path.rstrip("/").split("/")[-1] or "External paper"
    authors = ", ".join(meta.get("citation_author", []))
    abstract = first("citation_abstract", "description", "dc.description")
    pdf_url = first("citation_pdf_url")
    if pdf_url:
        pdf_url = urljoin(final_url, pdf_url)
    venue = first("citation_conference_title", "citation_journal_title")
    year_text = first("citation_publication_date", "citation_date")
    year_match = re.search(r"(?:19|20)\d{2}", year_text)
    year = int(year_match.group(0)) if year_match else None

    return PaperSource(
        paper_id=final_url,
        title=" ".join(title.split()),
        authors=" ".join(authors.split()),
        venue=" ".join(venue.split()),
        year=year,
        paper_url=final_url,
        pdf_url=pdf_url,
        abstract=" ".join(abstract.split()),
        source_kind="url",
    )
