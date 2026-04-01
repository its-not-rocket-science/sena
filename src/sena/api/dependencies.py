from __future__ import annotations

from fastapi import Request

from sena.api.runtime import EngineState


def get_engine_state(request: Request) -> EngineState:
    return request.app.state.engine_state
