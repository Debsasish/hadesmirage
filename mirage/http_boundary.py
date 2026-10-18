from __future__ import annotations

import json
from typing import Any

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mirage.common import uid


class RequestBoundary:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uid()
        scope.setdefault("state", {})["request_id"] = request_id
        headers = dict(scope["headers"])
        if b"upgrade" in headers or b"text/event-stream" in headers.get(b"accept", b""):
            await JSONResponse(
                status_code=400,
                content={
                    "code": "UNSUPPORTED_STREAMING",
                    "message": "Streaming protocols are not supported",
                    "request_id": request_id,
                },
            )(scope, receive, send)
            return
        raw = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(raw) + len(chunk) > self.max_bytes:
                await JSONResponse(
                    status_code=413,
                    content={
                        "code": "BODY_TOO_LARGE",
                        "message": "Request exceeds the bounded input limit",
                        "request_id": request_id,
                    },
                )(scope, receive, send)
                return
            raw.extend(chunk)
            if not message.get("more_body", False):
                break
        if raw and headers.get(b"content-type", b"").startswith(b"application/json"):

            def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in items:
                    if key in result:
                        raise ValueError("Duplicate JSON key")
                    result[key] = value
                return result

            def reject_constant(_value: str) -> None:
                raise ValueError("Nonfinite number")

            try:
                json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
            except (ValueError, UnicodeDecodeError, RecursionError):
                await JSONResponse(
                    status_code=400,
                    content={
                        "code": "INVALID_JSON",
                        "message": "Malformed or ambiguous JSON",
                        "request_id": request_id,
                    },
                )(scope, receive, send)
                return
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(raw), "more_body": False}
            return await receive()

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                output_headers = list(message.get("headers", []))
                output_headers.extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                            b"img-src 'self' data:; font-src 'self'; connect-src 'self'; "
                            b"object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                        ),
                    ]
                )
                message["headers"] = output_headers
            await send(message)

        await self.app(scope, bounded_receive, secure_send)
