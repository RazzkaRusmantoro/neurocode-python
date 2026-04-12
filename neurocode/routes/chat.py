import os
from openai import OpenAI
from fastapi import APIRouter, HTTPException, Query

from neurocode.models.schemas import ChatRequest, CreateChatRequest, SendMessageRequest
from neurocode.config import mongodb_service, llm_service

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5-nano")

router = APIRouter(prefix="/chat", tags=["chat"])


def _get_openai_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        return None
    return OpenAI(api_key=api_key.strip())


                                                                               


@router.get("/list")
async def list_chats(
    user_id: str = Query(..., description="Current user id"),
    context_id: str | None = Query(None, description="Scope to a documentation context (e.g. repo-doc:org:repo, onboarding:org:pathSlug)"),
) -> dict:
    
    if not mongodb_service:
        raise HTTPException(status_code=503, detail="Database not configured")
    result = mongodb_service.list_chats_by_user(user_id, context_id=context_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to list chats"))
    chats = result.get("chats") or []
                                  
    for c in chats:
        u = c.get("updatedAt")
        if hasattr(u, "isoformat"):
            c["updatedAt"] = u.isoformat() + "Z"
    return {"chats": chats}


@router.get("/{chat_id}")
async def get_chat(
    chat_id: str,
    user_id: str = Query(..., description="Current user id"),
) -> dict:
    
    if not mongodb_service:
        raise HTTPException(status_code=503, detail="Database not configured")
    result = mongodb_service.get_chat(chat_id, user_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Chat not found"))
    return result


@router.post("")
async def create_chat(body: CreateChatRequest) -> dict:
    
    if not mongodb_service:
        raise HTTPException(status_code=503, detail="Database not configured")
    result = mongodb_service.create_chat(
        body.user_id,
        title=(body.title or "New chat"),
        context_id=body.context_id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to create chat"))
    return {"chatId": result["chat_id"], "chat": result["chat"]}


@router.post("/{chat_id}/message")
async def send_message(chat_id: str, body: SendMessageRequest) -> dict:
    
    if not mongodb_service:
        raise HTTPException(status_code=503, detail="Database not configured")
    client = _get_openai_client()
    if not client:
        raise HTTPException(status_code=503, detail="Chat not configured (OPENAI_API_KEY not set)")

    message = (body.message or "").strip()
    if not message:
        return {"reply": "Please send a non-empty message.", "chat": None}

                                            
    get_result = mongodb_service.get_chat(chat_id, body.user_id)
    if not get_result.get("success"):
        raise HTTPException(status_code=404, detail=get_result.get("error", "Chat not found"))
    chat = get_result.get("chat") or {}
    messages_doc = chat.get("messages") or []
    history_for_llm = []
    for m in messages_doc:
        role = m.get("role") or (m.get("sender") == "bot" and "assistant" or "user")
        content = (m.get("content") or m.get("text") or "").strip()
        if content and role in ("user", "assistant"):
            history_for_llm.append({"role": role, "content": content})

                                                                                                 
    system_content = "You are a helpful assistant. Answer concisely."
    if (body.documentation_content or "").strip():
        system_content = (
            "You are a helpful assistant. Answer questions based on the following documentation. "
            "If the answer is not in the documentation, say so. Stay concise.\n\n"
            "## Documentation\n\n"
            + (body.documentation_content or "").strip()
        )
    openai_messages = [
        {"role": "system", "content": system_content},
    ]
    for h in history_for_llm:
        openai_messages.append({"role": h["role"], "content": h["content"]})
    openai_messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=openai_messages,
        )
        reply = (
            (response.choices[0].message.content if response.choices else None)
            or ""
        ).strip() or "No response."
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {e}")

                                             
    title_if_first = message[:36].strip() + ("…" if len(message) > 36 else "") if message else None
    append_result = mongodb_service.append_chat_messages(
        chat_id,
        body.user_id,
        user_content=message,
        assistant_content=reply,
        title_if_first_user=title_if_first,
    )
    if not append_result.get("success"):
        raise HTTPException(status_code=500, detail=append_result.get("error", "Failed to save messages"))
    return {
        "reply": reply,
        "chat": append_result.get("chat"),
    }


                                                                     


@router.post("/send")
async def chat_legacy(request: ChatRequest) -> dict:
    
    client = _get_openai_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="Chat not configured (OPENAI_API_KEY not set)",
        )

    message = (request.message or "").strip()
    if not message:
        return {"reply": "Please send a non-empty message."}

    system_content = "You are a helpful assistant. Answer concisely."
    if (request.documentation_content or "").strip():
        system_content = (
            "You are a helpful assistant. Answer questions based on the following documentation. "
            "If the answer is not in the documentation, say so. Stay concise.\n\n"
            "## Documentation\n\n"
            + (request.documentation_content or "").strip()
        )
    history = request.history or []
    messages = [
        {"role": "system", "content": system_content},
    ]
    for m in history:
        if m.role in ("user", "assistant") and (m.content or "").strip():
            messages.append({"role": m.role, "content": m.content.strip()})
    messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
        )
        reply = (
            (response.choices[0].message.content if response.choices else None)
            or ""
        ).strip()
        return {"reply": reply or "No response."}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {e}")
