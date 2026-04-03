from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    user_id: int | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


_local = threading.local()


def set_request_context(ctx: RequestContext | None) -> None:
    _local.ctx = ctx


def get_request_context() -> RequestContext | None:
    return getattr(_local, "ctx", None)

