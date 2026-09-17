from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
import shutil
import json
import os

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from api.schemas import (
    SessionCreateRequest,
    SessionResponse,
    GoogleAuthRequest,
    GoogleAuthResponse,
    ChatRequest,
    ChatResponse,
    ResumeRequest,
)

from api.service import (
    run_text_chat_stream,
    run_resume_chat_stream,
    run_text_chat,
    run_file_chat,
    resume_chat,
    ensure_thread_owner,
)

from backend.agents.utils.db_utils import (
    get_or_create_user,
    create_thread,
)

from backend.agents.nodes.tools.tools import ingest_pdf


app = FastAPI(
    title="Math Teacher API",
    description="基于 LangGraph 的智能数学辅导 API",
    version="1.0.0",
)


# 开发阶段允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


UPLOAD_DIR = Path("uploads/api")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Google OAuth 的 client_id（与 .streamlit/secrets.toml 保持一致，
# 也可通过环境变量 GOOGLE_CLIENT_ID 覆盖）
GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID",
    "884766496961-u1tu99am3reupotc2f2rco5immul37sb.apps.googleusercontent.com",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "math-teacher-api",
    }


# ---------------------------------------------------------
# Auth
# ---------------------------------------------------------

@app.post(
    "/api/v1/auth/google",
    response_model=GoogleAuthResponse,
)
def auth_google(req: GoogleAuthRequest):
    """
    校验前端 Google Identity Services 返回的 ID token (JWT)，
    解码出 email / name，映射为稳定的 student_id 以隔离学生画像。
    """

    try:
        idinfo = id_token.verify_oauth2_token(
            req.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )

        email = idinfo.get("email")
        if not email:
            raise HTTPException(
                status_code=400,
                detail="无法从 Google 凭证中获取邮箱",
            )

        display_name = idinfo.get("name") or email.split("@")[0]

        student_id = get_or_create_user(
            email=email,
            display_name=display_name,
        )

        thread_id = create_thread(student_id)

        return {
            "student_id": student_id,
            "thread_id": thread_id,
            "email": email,
            "display_name": display_name,
        }

    except HTTPException:
        raise

    except ValueError as exc:
        # verify_oauth2_token 校验失败（签名/过期/aud 不匹配等）
        raise HTTPException(
            status_code=401,
            detail=f"Google 凭证校验失败: {exc}",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ---------------------------------------------------------
# Session
# ---------------------------------------------------------

@app.post(
    "/api/v1/sessions",
    response_model=SessionResponse,
)
def create_session(req: SessionCreateRequest):

    try:
        student_id = get_or_create_user(
            email=req.email,
            display_name=req.display_name,
        )

        thread_id = create_thread(student_id)

        return {
            "student_id": student_id,
            "thread_id": thread_id,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ---------------------------------------------------------
# Text Chat
# ---------------------------------------------------------

@app.post(
    "/api/v1/chat/text",
    response_model=ChatResponse,
)
def chat_text(req: ChatRequest):

    try:
        return run_text_chat(
            student_id=req.student_id,
            thread_id=req.thread_id,
            message=req.message,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ---------------------------------------------------------
# Streaming Text Chat (SSE)
# ---------------------------------------------------------

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/v1/chat/text/stream")
def chat_text_stream(req: ChatRequest):
    """
    Streaming variant of /api/v1/chat/text.

    Emits Server-Sent Events so the frontend can render the agent's
    step-by-step thinking ("thinking" events) and final answer ("done").
    """

    def event_stream():
        try:
            for event in run_text_chat_stream(
                student_id=req.student_id,
                thread_id=req.thread_id,
                message=req.message,
            ):
                yield _sse(event)
        except ValueError as exc:
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------
# Streaming HITL resume (SSE)
# ---------------------------------------------------------

@app.post("/api/v1/hitl/resume/stream")
def hitl_resume_stream(req: ResumeRequest):

    def event_stream():
        try:
            for event in run_resume_chat_stream(
                student_id=req.student_id,
                thread_id=req.thread_id,
                response=req.response,
            ):
                yield _sse(event)
        except ValueError as exc:
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------
# 
# ---------------------------------------------------------
# Image / Audio
# ---------------------------------------------------------

@app.post(
    "/api/v1/chat/file",
    response_model=ChatResponse,
)
def chat_file(
    student_id: Annotated[str, Form()],
    thread_id: Annotated[str, Form()],
    input_type: Annotated[
        Literal["image", "audio"],
        Form(),
    ],
    file: UploadFile = File(...),
):

    try:
        ensure_thread_owner(
            student_id,
            thread_id,
        )

        suffix = Path(
            file.filename or ""
        ).suffix.lower()

        safe_name = (
            f"{uuid4().hex}{suffix}"
        )

        file_path = (
            UPLOAD_DIR / safe_name
        )

        with file_path.open("wb") as output:
            shutil.copyfileobj(
                file.file,
                output,
            )

        if input_type == "image":
            return run_file_chat(
                student_id,
                thread_id,
                image_path=str(file_path),
            )

        return run_file_chat(
            student_id,
            thread_id,
            audio_path=str(file_path),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ---------------------------------------------------------
# HITL resume
# ---------------------------------------------------------

@app.post(
    "/api/v1/hitl/resume",
    response_model=ChatResponse,
)
def hitl_resume(req: ResumeRequest):

    try:
        return resume_chat(
            student_id=req.student_id,
            thread_id=req.thread_id,
            response=req.response,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ---------------------------------------------------------
# PDF RAG
# ---------------------------------------------------------

@app.post("/api/v1/materials/pdf")
def upload_pdf(
    student_id: Annotated[str, Form()],
    thread_id: Annotated[str, Form()],
    file: UploadFile = File(...),
):

    try:
        ensure_thread_owner(
            student_id,
            thread_id,
        )

        if not (
            file.filename or ""
        ).lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only PDF is supported",
            )

        file_bytes = file.file.read()

        result = ingest_pdf(
            file_bytes=file_bytes,
            thread_id=thread_id,
            filename=file.filename or "document.pdf",
        )

        return {
            "status": "success",
            **result,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )