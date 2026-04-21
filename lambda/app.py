"""AWS Lambda entrypoint for nanobanana MCP server.

Exposes the upstream FastMCP server via Streamable HTTP (stateless JSON mode)
wrapped with Mangum so it can be invoked behind a Lambda Function URL or API
Gateway.

Env vars consumed here (Lambda / SAM template sets these):
    GEMINI_API_KEY  - required, passed straight through to the upstream server
    MCP_AUTH_TOKEN  - optional, if set the handler requires
                      `Authorization: Bearer <token>` on every request
    IMAGE_OUTPUT_DIR - optional, defaults to /tmp/nanobanana (Lambda scratch)
    LOG_LEVEL       - optional, forwarded to upstream
"""

from __future__ import annotations

import hmac
import logging
import os

os.environ.setdefault("FASTMCP_TRANSPORT", "http")
os.environ.setdefault("IMAGE_OUTPUT_DIR", "/tmp/nanobanana")

from mangum import Mangum
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from nanobanana_mcp_server.server import create_wrapper_app


log = logging.getLogger(__name__)


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


def _build_asgi_app():
    wrapper = create_wrapper_app()
    asgi = wrapper.server.http_app(
        path="/mcp",
        transport="http",
        stateless_http=True,
        json_response=True,
    )
    asgi.add_middleware(
        BearerAuthMiddleware, expected_token=os.environ.get("MCP_AUTH_TOKEN")
    )
    return asgi


_asgi_app = _build_asgi_app()

handler = Mangum(_asgi_app, lifespan="on", api_gateway_base_path="/")
