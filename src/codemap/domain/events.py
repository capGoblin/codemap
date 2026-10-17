from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventKind = Literal[
    "step_started", "hop_found", "hop_verified", "phase_split", "warning", "finished"
]


class Event(BaseModel):
    trace_id: str
    kind: EventKind
    message: str
    data: dict[str, object] = Field(default_factory=dict)
    at: datetime
