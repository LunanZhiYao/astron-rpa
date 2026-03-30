import json
from urllib.parse import urljoin

from fastapi import APIRouter, HTTPException, Request
from app.config import get_settings
from app.models.smart_component import SmartChatResponse
from app.schemas.chat import ChatCompletionParam
from app.services.chat import chat_completions

router = APIRouter(
    prefix="/cua",
    tags=["计算机使用代理"],
)

CUA_KEY = get_settings().CUA_API_KEY
CUA_ENDPOINT = urljoin(get_settings().CUA_BASE_URL, "chat/completions")


async def _extract_messages_from_request(request: Request) -> list[dict]:
    """
    Accept both JSON body and raw text/bytes JSON body.
    Supported payload formats:
    - [{"role":"user","content":"..."}]
    - {"messages":[{"role":"user","content":"..."}]}
    """
    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(status_code=422, detail="Request body is empty")

    content_type = (request.headers.get("content-type") or "").lower()
    data = None

    # Standard JSON request
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid JSON body: {exc}") from exc
    else:
        # Fallback for clients not sending content-type but posting JSON text.
        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported content-type '{content_type or 'None'}' or invalid JSON body",
            ) from exc

    if isinstance(data, dict):
        messages = data.get("messages")
    elif isinstance(data, list):
        messages = data
    else:
        raise HTTPException(status_code=422, detail="Body must be a JSON object or JSON array")

    if not isinstance(messages, list):
        raise HTTPException(status_code=422, detail="'messages' must be a list")
    if not all(isinstance(item, dict) for item in messages):
        raise HTTPException(status_code=422, detail="Each message must be a JSON object")

    return messages


@router.post("/chat/stream")
async def cua_chat_stream(request: Request):
    messages = await _extract_messages_from_request(request)
    llm_params = ChatCompletionParam(
        model="QianYi10",
        stream=True,
        temperature=0,
        max_tokens=8192,
        messages=messages,
    )

    return await chat_completions(llm_params, CUA_KEY, CUA_ENDPOINT)


@router.post("/chat", response_model=SmartChatResponse)
async def cua_chat(request: Request):
    messages = await _extract_messages_from_request(request)
    llm_params = ChatCompletionParam(
        model="QianYi10",
        stream=False,
        temperature=0.2,
        max_tokens=128000,
        messages=messages,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False},
        }, 
    )

    chat_result = await chat_completions(llm_params, CUA_KEY, CUA_ENDPOINT)

    return SmartChatResponse(data=json.loads(chat_result.body), code=200, success=True)
