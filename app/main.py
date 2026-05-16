from __future__ import annotations

import os

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import json
from contextlib import asynccontextmanager
from pathlib import Path

import logfire
import uvicorn
from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from chat.schemas import (
    ChatMessage,
    ChatRequest,
    CreateConversationResponse,
    ModelOption,
    UpdateConversationRequest,
)
from chat.service import ChatService, chat_service_lifespan
from ingestion.observability import configure_logfire, configure_logging
from utils.config import load_config
from utils.db.d1 import D1Database
from utils.observability import logfire_enabled

load_dotenv()

CONFIG_PATH = "config.toml"
INDEX_PATH = Path(__file__).with_name("index.html")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config(CONFIG_PATH)
    configure_logging(cfg)
    Path(cfg.kirana.chat_log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(cfg.kirana.chat_log_file, level=cfg.log_level, rotation="5 MB")
    configure_logfire()
    if logfire_enabled():
        logfire.instrument_fastapi(app)
        logfire.instrument_openai()

    d1 = D1Database.from_env(cfg)
    app.state.d1 = d1
    async with chat_service_lifespan(cfg, d1) as service:
        app.state.chat_service = service
        logger.info("chat service ready")
        yield


app = FastAPI(lifespan=lifespan)


def chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(INDEX_PATH)


@app.get("/api/models", response_model=list[ModelOption])
async def models(request: Request) -> list[dict[str, str]]:
    return chat_service(request).model_options()


@app.get("/api/conversations")
async def conversations(request: Request):
    return await chat_service(request).list_conversations()


@app.post("/api/conversations", response_model=CreateConversationResponse)
async def create_conversation(request: Request) -> CreateConversationResponse:
    conversation = await chat_service(request).create_conversation()
    return CreateConversationResponse(conversation=conversation)


@app.patch("/api/conversations/{thread_id}", response_model=CreateConversationResponse)
async def update_conversation(
    thread_id: str, payload: UpdateConversationRequest, request: Request
) -> CreateConversationResponse:
    service = chat_service(request)
    try:
        conversation = await service.update_conversation_title(thread_id, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return CreateConversationResponse(conversation=conversation)


@app.delete("/api/conversations/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(thread_id: str, request: Request) -> Response:
    deleted = await chat_service(request).delete_conversation(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/conversations/{thread_id}/messages",
    response_model=list[ChatMessage],
    response_model_exclude_none=True,
)
async def conversation_messages(thread_id: str, request: Request) -> list[ChatMessage]:
    service = chat_service(request)
    if await service.get_conversation(thread_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return await service.messages(thread_id)


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    service = chat_service(request)

    async def event_generator():
        try:
            async for event in service.chat_stream(
                message=payload.message,
                model_name=payload.model,
                thread_id=payload.thread_id,
                system_prompt=payload.system_prompt,
                tools_enabled=payload.tools_enabled,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        except Exception as exc:
            logger.exception("chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/image/stream")
async def chat_image_stream(
    request: Request,
    model: str = Form(...),
    message: str = Form(default=""),
    thread_id: str | None = Form(default=None),
    system_prompt: str | None = Form(default=None),
    tools_enabled: bool = Form(default=True),
    image: UploadFile = File(...),
) -> StreamingResponse:
    service = chat_service(request)

    async def event_generator():
        try:
            image_bytes = await image.read()
            async for event in service.chat_stream(
                message=message,
                model_name=model,
                thread_id=thread_id,
                system_prompt=system_prompt,
                tools_enabled=tools_enabled,
                image_bytes=image_bytes,
                image_filename=image.filename,
                image_content_type=image.content_type,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        except Exception as exc:
            logger.exception("image chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
