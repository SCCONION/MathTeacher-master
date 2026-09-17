from typing import Any
from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    email: str
    display_name: str = "Demo Student"


class SessionResponse(BaseModel):
    student_id: str
    thread_id: str


class GoogleAuthRequest(BaseModel):
    credential: str = Field(min_length=1)  # Google ID token (JWT)


class GoogleAuthResponse(BaseModel):
    student_id: str
    thread_id: str
    email: str
    display_name: str


class ChatRequest(BaseModel):
    student_id: str
    thread_id: str
    message: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    student_id: str
    thread_id: str
    response: dict[str, Any]


class ChatResponse(BaseModel):
    thread_id: str
    status: str
    answer: str | None = None
    intent: str | None = None
    topic: str | None = None
    hitl: dict[str, Any] | None = None
    activity: list[dict[str, Any]] = []