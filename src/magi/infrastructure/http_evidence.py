"""Fail-closed HTTPS evidence retrieval with SSRF and size controls."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from datetime import datetime
from html.parser import HTMLParser
import httpx
from pydantic import Field, field_validator

from magi.application import (
    EvidenceRetrievalError,
    EvidenceSourceRequest,
    RetrievedEvidence,
)
from magi.domain.models import MagiModel, utc_now


Resolver = Callable[[str], Awaitable[tuple[str, ...]]]
DNS_HOST_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)


class EvidenceGatewayPolicy(MagiModel):
    """Deployment-owned bounds; an empty host set denies every request."""

    allowed_hosts: frozenset[str] = frozenset()
    timeout_seconds: float = Field(default=8.0, ge=0.5, le=30.0)
    max_response_bytes: int = Field(default=20_000, ge=1_000, le=1_000_000)
    allowed_content_types: frozenset[str] = frozenset(
        {"text/plain", "text/html", "application/json"}
    )

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_hosts(cls, hosts: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(_normalize_host(host) for host in hosts)
        if any(DNS_HOST_PATTERN.fullmatch(host) is None for host in normalized):
            raise ValueError("evidence allowlist entries must be exact DNS hosts")
        return normalized


class HttpEvidenceGateway:
    """Retrieve bounded textual evidence without redirects, proxies, or credentials."""

    def __init__(
        self,
        policy: EvidenceGatewayPolicy,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._policy = policy
        self._client = client
        self._resolver = resolver or _resolve_host
        self._clock = clock

    async def retrieve(self, request: EvidenceSourceRequest) -> RetrievedEvidence:
        host = _normalize_host(request.url.host or "")
        if host not in self._policy.allowed_hosts:
            raise EvidenceRetrievalError("evidence source is not allowlisted")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise EvidenceRetrievalError("literal IP evidence sources are forbidden")

        try:
            resolved = frozenset(await self._resolver(host))
        except (OSError, TimeoutError) as exc:
            raise EvidenceRetrievalError("evidence source resolution failed") from exc
        if not resolved or any(not _public_address(address) for address in resolved):
            raise EvidenceRetrievalError("evidence source did not resolve publicly")

        if self._client is not None:
            return await self._retrieve_with_client(request, self._client, resolved)
        timeout = httpx.Timeout(self._policy.timeout_seconds)
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "MAGI-Evidence-Gateway/1.0"},
        ) as client:
            return await self._retrieve_with_client(request, client, resolved)

    async def _retrieve_with_client(
        self,
        request: EvidenceSourceRequest,
        client: httpx.AsyncClient,
        resolved: frozenset[str],
    ) -> RetrievedEvidence:
        try:
            async with client.stream("GET", str(request.url)) as response:
                if response.status_code != 200:
                    raise EvidenceRetrievalError("evidence source returned no content")
                peer = _peer_address(response)
                if peer not in resolved or not _public_address(peer):
                    raise EvidenceRetrievalError("evidence connection peer is invalid")
                content_type = response.headers.get("content-type", "")
                media_type = content_type.partition(";")[0].strip().lower()
                if media_type not in self._policy.allowed_content_types:
                    raise EvidenceRetrievalError("evidence content type is not allowed")
                declared = response.headers.get("content-length")
                if declared is not None and int(declared) > self._policy.max_response_bytes:
                    raise EvidenceRetrievalError("evidence response exceeds size limit")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._policy.max_response_bytes:
                        raise EvidenceRetrievalError("evidence response exceeds size limit")
        except EvidenceRetrievalError:
            raise
        except (httpx.HTTPError, UnicodeError, ValueError) as exc:
            raise EvidenceRetrievalError("evidence retrieval failed") from exc

        try:
            text = _decode(bytes(body), content_type)
            if media_type == "text/html":
                text = _html_text(text)
            excerpt = _normalize_text(text)
        except EvidenceRetrievalError:
            raise
        except (UnicodeError, ValueError) as exc:
            raise EvidenceRetrievalError("evidence content could not be decoded") from exc
        if not excerpt:
            raise EvidenceRetrievalError("evidence source contained no usable text")
        captured_at = self._clock()
        if captured_at.tzinfo is None:
            raise EvidenceRetrievalError("evidence gateway clock is invalid")
        return RetrievedEvidence(
            source_type="retrieved_https",
            source=str(request.url),
            captured_at=captured_at,
            excerpt=excerpt,
            content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            classification=request.classification,
        )


async def _resolve_host(host: str) -> tuple[str, ...]:
    def resolve() -> tuple[str, ...]:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return tuple(sorted({record[4][0] for record in records}))

    return await asyncio.to_thread(resolve)


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").encode("idna").decode("ascii").lower()


def _public_address(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _peer_address(response: httpx.Response) -> str:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        raise EvidenceRetrievalError("evidence connection peer is unavailable")
    address = stream.get_extra_info("server_addr")
    if not isinstance(address, tuple) or not address:
        raise EvidenceRetrievalError("evidence connection peer is unavailable")
    return str(address[0])


def _decode(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for item in content_type.split(";")[1:]:
        key, _, value = item.strip().partition("=")
        if key.lower() == "charset" and value:
            charset = value.strip('"').lower()
    if charset not in {"utf-8", "utf8", "us-ascii", "ascii"}:
        raise EvidenceRetrievalError("evidence charset is not allowed")
    return body.decode(charset, errors="strict")


def _normalize_text(value: str) -> str:
    lines = (" ".join(line.split()) for line in value.splitlines())
    return "\n".join(line for line in lines if line).strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _html_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return "\n".join(parser.parts)
