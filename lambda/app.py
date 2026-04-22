"""AWS Lambda entrypoint for nanobanana MCP server.

Exposes the upstream FastMCP server via Streamable HTTP (stateless JSON mode)
wrapped with Mangum so it can be invoked behind a Lambda Function URL or API
Gateway.

Generated images are uploaded to an S3 bucket and a presigned download URL is
injected into the JSON metadata of the tool response, so the calling LLM can
fetch the file (Lambda /tmp is per-instance and not reachable across calls).

Env vars consumed here (Lambda / SAM template sets these):
    GEMINI_API_KEY              - required, passed straight through
    MCP_AUTH_TOKEN              - optional, requires `Authorization: Bearer <token>`
    IMAGE_OUTPUT_DIR            - optional, defaults to /tmp/nanobanana
    IMAGE_S3_BUCKET             - optional, enables S3 upload + download_url injection
    IMAGE_S3_PREFIX             - optional, defaults to "images/"
    IMAGE_PRESIGN_TTL_SECONDS   - optional, defaults to 3600
    IMAGE_RETENTION_DAYS        - optional, advisory only (used in instructions text)
    LOG_LEVEL                   - optional, forwarded to upstream
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

os.environ.setdefault("FASTMCP_TRANSPORT", "http")
os.environ.setdefault("IMAGE_OUTPUT_DIR", "/tmp/nanobanana")

import boto3
from mangum import Mangum
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from nanobanana_mcp_server.server import create_wrapper_app


log = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("IMAGE_S3_BUCKET")
S3_PREFIX = os.environ.get("IMAGE_S3_PREFIX", "images/")
PRESIGN_TTL = int(os.environ.get("IMAGE_PRESIGN_TTL_SECONDS", "3600"))
IMAGE_RETENTION_DAYS = int(os.environ.get("IMAGE_RETENTION_DAYS", "7"))
IMAGE_OUTPUT_DIR = Path(os.environ["IMAGE_OUTPUT_DIR"]).resolve()

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_SAFE_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_s3_client = None


def _s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _safe_basename(original: str, suffix: str) -> str:
    """Return a basename guaranteed safe to interpolate into a shell command.

    If `original` already matches a strict allow-list (alnum + `._-`, leading
    alnum, length <= 128) we keep it; otherwise we replace it with a uuid so
    the LLM never substitutes attacker-controlled bytes into `-o <name>`.
    """
    if _SAFE_BASENAME_RE.match(original) and "/" not in original:
        return original
    safe_suffix = suffix if _SAFE_BASENAME_RE.match("a" + suffix) else ".bin"
    return f"image-{uuid.uuid4().hex[:12]}{safe_suffix}"


def _upload_and_presign(local_path: str) -> tuple[str, str] | None:
    """Upload a generated image and return `(presigned_url, safe_filename)`.

    Path is anchored under `IMAGE_OUTPUT_DIR` and symlinks are rejected so a
    compromised upstream tool cannot trick us into uploading e.g. /etc/passwd.
    """
    if not S3_BUCKET:
        return None
    try:
        p = Path(local_path)
        if p.is_symlink():
            log.warning("s3 upload rejected (symlink): %s", local_path)
            return None
        resolved = p.resolve(strict=True)
    except (OSError, RuntimeError):
        log.warning("s3 upload skipped: cannot resolve %s", local_path)
        return None
    if not resolved.is_file():
        log.warning("s3 upload skipped: %s not a regular file", local_path)
        return None
    try:
        resolved.relative_to(IMAGE_OUTPUT_DIR)
    except ValueError:
        log.warning(
            "s3 upload rejected (outside IMAGE_OUTPUT_DIR=%s): %s",
            IMAGE_OUTPUT_DIR,
            resolved,
        )
        return None

    safe_name = _safe_basename(resolved.name, resolved.suffix.lower())
    key = f"{S3_PREFIX}{uuid.uuid4().hex}-{safe_name}"
    content_type = _MIME_BY_SUFFIX.get(
        resolved.suffix.lower(), "application/octet-stream"
    )
    try:
        _s3().upload_file(
            str(resolved),
            S3_BUCKET,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "ContentDisposition": f'attachment; filename="{safe_name}"',
            },
        )
        url = _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=PRESIGN_TTL,
        )
        return url, safe_name
    except Exception:
        log.exception("s3 upload failed for %s", resolved)
        return None


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a matching `Authorization: Bearer <token>` header.

    Disabled (pass-through) when MCP_AUTH_TOKEN is unset so local invocations
    (e.g. `sam local start-api`) still work.
    """

    def __init__(self, app, expected_token: str | None) -> None:
        super().__init__(app)
        self._expected = expected_token

    async def dispatch(self, request, call_next):
        if self._expected:
            header = request.headers.get("authorization", "")
            prefix = "Bearer "
            if not header.startswith(prefix) or not hmac.compare_digest(
                header[len(prefix) :], self._expected
            ):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


class S3AugmentMiddleware(BaseHTTPMiddleware):
    """Upload generated image files to S3 and inject `download_url` into the
    JSON metadata of `tools/call` responses. No-op when IMAGE_S3_BUCKET is
    unset, when the response is not JSON, or when no image paths are found."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if not S3_BUCKET:
            return response
        if "application/json" not in response.headers.get("content-type", ""):
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return self._passthrough(body, response)

        try:
            mutated = self._augment(payload)
        except Exception:
            log.exception("s3 augment failed; returning original body")
            return self._passthrough(body, response)

        if not mutated:
            return self._passthrough(body, response)

        new_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(response.headers)
        headers["content-length"] = str(len(new_body))
        return Response(
            content=new_body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    @staticmethod
    def _passthrough(body: bytes, response) -> Response:
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    def _augment(self, payload: Any) -> bool:
        items = payload if isinstance(payload, list) else [payload]
        mutated_any = False
        for item in items:
            if not isinstance(item, dict):
                continue
            result = item.get("result")
            if not isinstance(result, dict):
                continue
            content = result.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                text = block.get("text")
                if not isinstance(text, str):
                    continue
                try:
                    inner = json.loads(text)
                except Exception:
                    continue
                if not isinstance(inner, dict):
                    continue
                images = inner.get("images")
                if not isinstance(images, list) or not images:
                    continue

                changed = False
                for img in images:
                    if not isinstance(img, dict) or img.get("download_url"):
                        continue
                    full_path = img.get("full_path")
                    if not isinstance(full_path, str):
                        continue
                    upload = _upload_and_presign(full_path)
                    if upload:
                        url, safe_name = upload
                        img["download_url"] = url
                        img["download_url_expires_in_seconds"] = PRESIGN_TTL
                        img["safe_filename"] = safe_name
                        changed = True

                if changed:
                    block["text"] = json.dumps(inner, ensure_ascii=False)
                    structured = result.get("structuredContent")
                    if isinstance(structured, dict):
                        structured["images"] = inner.get("images")
                    mutated_any = True
        return mutated_any


def _inject_download_instructions(wrapper) -> None:
    if not S3_BUCKET:
        return
    extra = (
        "\n\n## Image download (Lambda + S3)\n"
        f"Generated images are auto-uploaded to S3. Each entry in the tool "
        f"response's `images[]` array carries:\n"
        f"  - `download_url` — HTTPS presigned GET URL, valid {PRESIGN_TTL} seconds.\n"
        f"  - `safe_filename` — server-sanitised filename, guaranteed to match "
        f"`^[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}$`.\n\n"
        f"After every `generate_image` call you MUST download each image into "
        f"the user's current working directory using **the value of "
        f"`safe_filename` verbatim** as the output filename. Use a single "
        f"shell call shaped exactly like:\n"
        f'    curl -fsSL --output "$SAFE_FILENAME" "$DOWNLOAD_URL"\n'
        f"where `$SAFE_FILENAME` is the `safe_filename` value and "
        f"`$DOWNLOAD_URL` is the `download_url` value. Do not interpolate "
        f"`full_path`, `basename`, or any other field into the shell command. "
        f"If `safe_filename` is missing or fails the regex above, refuse to "
        f"download and surface the response to the user instead. Do this "
        f"automatically without asking. Files are auto-deleted from S3 after "
        f"{IMAGE_RETENTION_DAYS} days — download promptly."
    )
    wrapper.server.instructions = (wrapper.server.instructions or "") + extra


def _build_asgi_app():
    wrapper = create_wrapper_app()
    _inject_download_instructions(wrapper)
    asgi = wrapper.server.http_app(
        path="/mcp",
        transport="http",
        stateless_http=True,
        json_response=True,
    )
    asgi.add_middleware(S3AugmentMiddleware)
    asgi.add_middleware(
        BearerAuthMiddleware, expected_token=os.environ.get("MCP_AUTH_TOKEN")
    )
    return asgi


_asgi_app = _build_asgi_app()

handler = Mangum(_asgi_app, lifespan="on", api_gateway_base_path="/")
