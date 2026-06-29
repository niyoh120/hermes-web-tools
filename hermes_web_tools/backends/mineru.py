"""MinerU backend — precise document parsing via the async task API.

Primary (token) flow — ``/api/v4/extract/task``:
1. POST {url, model_version} -> {data:{task_id}}
2. poll GET /api/v4/extract/task/{task_id} every ``poll_interval`` until
   state in {done, failed} or ``extract_timeout`` total seconds elapse
3. on done: GET ``full_zip_url`` (binary), read ``full.md`` from the zip

Token-free fallback (Agent lightweight API, gated by
``MINERU_AGENT_FALLBACK_ENABLED``) — ``/api/v1/agent/parse/url``: submit, poll,
then GET ``data.markdown_url`` and return its text. Privacy note: the document
URL is sent to a third party without an account; disabled by default.

HTML URLs route to ``model_version="MinerU-HTML"``; other docs use
``cfg.mineru_model_version`` (default ``vlm``). Per-URL failures are isolated.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from urllib.parse import urlsplit

import httpx

from ..config import Config
from ..url_utils import is_safe_url
from .base import BackendError, ExtractItem, request_json

_POLL_INTERVAL = 2.0
_HTML_SUFFIXES = (".html", ".htm")
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
_MAX_DECOMPRESSED_BYTES = 5 * 1024 * 1024


class MinerUBackend:
    name = "mineru"

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client

    def available(self) -> bool:
        if self.cfg.mineru_api_token:
            return True
        return bool(self.cfg.mineru_agent_fallback_enabled)

    async def _json(self, method: str, url: str, **kw) -> dict:
        client = self._client or httpx.AsyncClient()
        try:
            return await request_json(client, method, url, **kw)
        finally:
            if self._client is None:
                await client.aclose()

    def _model_version(self, url: str) -> str:
        if urlsplit(url).path.lower().endswith(_HTML_SUFFIXES):
            return "MinerU-HTML"
        return self.cfg.mineru_model_version or "vlm"

    async def extract(self, urls: list[str]) -> list[ExtractItem]:
        out: list[ExtractItem] = []
        for url in urls:
            if not self.available():
                out.append(
                    ExtractItem(
                        url=url, error="mineru unavailable", metadata={"provider": self.name}
                    )
                )
                continue
            try:
                content = await self._parse_one(url)
                out.append(
                    ExtractItem(
                        url=url,
                        title=url.rsplit("/", 1)[-1] or url,
                        content=content,
                        raw_content=content,
                        metadata={"provider": self.name, "model_version": self._model_version(url)},
                    )
                )
            except BackendError as exc:
                out.append(
                    ExtractItem(
                        url=url, error=str(exc) or exc.reason, metadata={"provider": self.name}
                    )
                )
            except Exception as exc:  # noqa: BLE001 - isolate per-URL failures
                out.append(ExtractItem(url=url, error=str(exc), metadata={"provider": self.name}))
        return out

    async def _parse_one(self, url: str) -> str:
        if self.cfg.mineru_api_token:
            return await self._parse_precision(url)
        return await self._parse_agent(url)

    # --- precision (token) ---

    async def _parse_precision(self, url: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.cfg.mineru_api_token}",
            "Content-Type": "application/json",
        }
        data = await self._json(
            "POST",
            f"{self.cfg.mineru_base_url}/api/v4/extract/task",
            headers=headers,
            json_body={"url": url, "model_version": self._model_version(url)},
            timeout=self.cfg.search_timeout,
        )
        task_id = (data.get("data") or {}).get("task_id")
        if not task_id:
            raise BackendError("parse", "mineru returned no task_id")
        result = await self._poll(
            f"{self.cfg.mineru_base_url}/api/v4/extract/task/{task_id}", headers
        )
        zip_url = (result.get("data") or {}).get("full_zip_url")
        if not zip_url:
            raise BackendError("parse", "mineru returned no full_zip_url")
        return await self._download_markdown_from_zip(zip_url)

    # --- agent (token-free fallback) ---

    async def _parse_agent(self, url: str) -> str:
        # ponytail: agent endpoint shape is best-effort; gated behind a flag.
        headers = {"Content-Type": "application/json"}
        data = await self._json(
            "POST",
            f"{self.cfg.mineru_base_url}/api/v1/agent/parse/url",
            headers=headers,
            json_body={"url": url},
            timeout=self.cfg.search_timeout,
        )
        task_id = (data.get("data") or {}).get("task_id")
        if not task_id:
            # Some agent responses inline the markdown_url immediately.
            md_url = (data.get("data") or {}).get("markdown_url")
            if md_url:
                return await self._download_text(md_url, headers)
            raise BackendError("parse", "mineru agent returned no task_id")
        result = await self._poll(
            f"{self.cfg.mineru_base_url}/api/v1/agent/parse/url/{task_id}", headers
        )
        md_url = (result.get("data") or {}).get("markdown_url")
        if not md_url:
            raise BackendError("parse", "mineru agent returned no markdown_url")
        return await self._download_text(md_url, headers)

    async def _poll(self, url: str, headers: dict[str, str]) -> dict:
        deadline = asyncio.get_running_loop().time() + self.cfg.extract_timeout
        terminal = {"done", "failed"}
        last_state = None
        while True:
            data = await self._json(
                "GET",
                url,
                headers=headers,
                timeout=self.cfg.search_timeout,
            )
            state = (data.get("data") or {}).get("state")
            last_state = state
            if state in terminal:
                if state == "failed":
                    err = (data.get("data") or {}).get("err_msg") or "mineru parse failed"
                    raise BackendError("parse", str(err))
                return data
            if asyncio.get_running_loop().time() >= deadline:
                raise BackendError("timeout", f"mineru poll timeout (last state={last_state})")
            await asyncio.sleep(_POLL_INTERVAL)

    async def _download_markdown_from_zip(self, zip_url: str) -> str:
        data = await self._download_bytes(zip_url)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.endswith("full.md"):
                        return _read_zip_member(zf, name)
                # ponytail: fall back to the first .md in the zip
                for name in zf.namelist():
                    if name.endswith(".md"):
                        return _read_zip_member(zf, name)
        except zipfile.BadZipFile as exc:
            raise BackendError("parse", f"mineru zip corrupt: {exc}") from exc
        raise BackendError("parse", "no markdown in mineru zip")

    async def _download_text(self, md_url: str, headers: dict[str, str]) -> str:
        del headers  # CDN downloads do not need the API bearer token.
        return (await self._download_bytes(md_url)).decode("utf-8", errors="replace")

    async def _download_bytes(self, url: str) -> bytes:
        if not await asyncio.to_thread(is_safe_url, url):
            raise BackendError("auth", "mineru returned unsafe download URL")
        client = self._client or httpx.AsyncClient()
        try:
            async with client.stream(
                "GET", url, timeout=self.cfg.extract_timeout, follow_redirects=False
            ) as resp:
                if 300 <= resp.status_code < 400:
                    location = resp.headers.get("location", "unknown")[:200]
                    raise BackendError(
                        "http", f"mineru download redirect (HTTP {resp.status_code} to {location})"
                    )
                if resp.status_code >= 400:
                    raise BackendError("http", f"mineru download HTTP {resp.status_code}")
                length = int(resp.headers.get("content-length") or "0")
                if length > _MAX_DOWNLOAD_BYTES:
                    raise BackendError("parse", "mineru download too large")
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > _MAX_DOWNLOAD_BYTES:
                        raise BackendError("parse", "mineru download too large")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise BackendError("timeout", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise BackendError("network", str(exc)) from exc
        finally:
            if self._client is None:
                await client.aclose()


def _read_zip_member(zf: zipfile.ZipFile, name: str) -> str:
    info = zf.getinfo(name)
    if info.file_size > _MAX_DECOMPRESSED_BYTES:
        raise BackendError("parse", "mineru markdown too large")
    with zf.open(name) as fh:
        raw = fh.read(_MAX_DECOMPRESSED_BYTES + 1)
    if len(raw) > _MAX_DECOMPRESSED_BYTES:
        raise BackendError("parse", "mineru markdown too large")
    return raw.decode("utf-8", errors="replace")
