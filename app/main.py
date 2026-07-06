import os
import subprocess
import sys

from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.services.retriever_service import RetrieverService
from app.services.confidence_service import decide_action
from app.services.template_reply_service import generate_template_reply
from app.services.room_inventory_service import RoomInventoryService
from app.services.chat_logger_service import log_chat, read_logs


app = FastAPI(title="Kost.cornerhouz RAG Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("frontend/index.html")

retriever = RetrieverService()
room_service = RoomInventoryService()

session_state = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    reply: str
    confidence: float
    action: str
    reason: str
    matched_faq_ids: list[str]
    needs_admin: bool
    source: str


def is_difference_question(message: str) -> bool:
    q = message.lower()
    keywords = [
        "bedanya",
        "beda nya",
        "apa bedanya",
        "perbedaannya",
        "beda apa",
        "kenapa beda",
        "kenapa harganya beda"
    ]
    return any(keyword in q for keyword in keywords)


def build_difference_reply() -> str:
    return (
        "Bedanya biasanya dari tipe kamar dan posisi jendela, kak. "
        "Kamar mandi dalam lebih mahal karena kamar mandinya private dan ada water heater. "
        "Untuk kamar mandi luar, kalau harganya di atas Rp1.000.000 berarti jendela depan, "
        "jadi lebih mahal dibanding kamar mandi luar biasa/jendela lorong. "
        "Kakak lebih cari yang budget 1 jutaan atau yang jendela depan?"
    )




ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")


def verify_admin(x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_TOKEN is not configured"
        )

    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Invalid admin token"
        )

    return True


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "Kost.cornerhouz RAG is running",
        "rooms_loaded": len(room_service.rooms),
        "available_rooms": len(room_service.available_rooms())
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session_id = request.session_id or "default"
    state = session_state.get(session_id, {})

    awaiting_room_location = state.get("awaiting_room_location", False)

    # 0. Follow-up question about price/type difference
    if is_difference_question(request.message):
        response = ChatResponse(
            reply=build_difference_reply(),
            confidence=1.0,
            action="FOLLOWUP_DIFFERENCE",
            reason="Answered price/type difference follow-up",
            matched_faq_ids=[],
            needs_admin=False,
            source="room_inventory"
        )

        log_chat({
            "session_id": session_id,
            "user_message": request.message,
            "bot_reply": response.reply,
            "source": response.source,
            "action": response.action,
            "confidence": response.confidence,
            "needs_admin": response.needs_admin,
            "matched_faq_ids": response.matched_faq_ids
        })

        return response

    # 1. Room availability / follow-up room questions
    if room_service.is_room_query(request.message) or awaiting_room_location:
        room_answer = room_service.answer_room_query(
            request.message,
            allow_followup_question=not awaiting_room_location
        )

        if room_answer.get("followup_needed"):
            session_state[session_id] = {
                "awaiting_room_location": True
            }
        else:
            session_state[session_id] = {
                "awaiting_room_location": False
            }

        response = ChatResponse(
            reply=room_answer["reply"],
            confidence=1.0,
            action="ROOM_LOOKUP",
            reason="Answered using structured room inventory",
            matched_faq_ids=[],
            needs_admin=room_answer.get("needs_admin", False),
            source="room_inventory"
        )

        log_chat({
            "session_id": session_id,
            "user_message": request.message,
            "bot_reply": response.reply,
            "source": response.source,
            "action": response.action,
            "confidence": response.confidence,
            "needs_admin": response.needs_admin,
            "matched_faq_ids": response.matched_faq_ids
        })

        return response

    # 2. General FAQ RAG questions
    results = retriever.search(request.message, top_k=5)
    decision = decide_action(results, request.message)

    top_faq = results[0]["faq"] if results else None

    reply = generate_template_reply(
        action=decision["action"],
        faq=top_faq,
        user_message=request.message
    )

    needs_admin = decision["action"] in [
        "ESCALATE",
        "ESCALATE_WITH_CONTEXT"
    ]

    response = ChatResponse(
        reply=reply,
        confidence=decision["confidence"],
        action=decision["action"],
        reason=decision["reason"],
        matched_faq_ids=[result["faq"]["id"] for result in results],
        needs_admin=needs_admin,
        source="faq_rag"
    )

    log_chat({
        "session_id": session_id,
        "user_message": request.message,
        "bot_reply": response.reply,
        "source": response.source,
        "action": response.action,
        "confidence": response.confidence,
        "needs_admin": response.needs_admin,
        "matched_faq_ids": response.matched_faq_ids
    })

    return response


@app.get("/admin/logs")
def get_logs(limit: int = 50, admin: bool = Depends(verify_admin)):
    return {
        "logs": read_logs(limit=limit)
    }


@app.post("/admin/reload-rooms")
def reload_rooms(admin: bool = Depends(verify_admin)):
    room_service.reload()

    return {
        "status": "success",
        "message": "Room inventory reloaded",
        "rooms_loaded": len(room_service.rooms),
        "available_rooms": len(room_service.available_rooms())
    }


@app.post("/admin/sync-faq")
def sync_faq(admin: bool = Depends(verify_admin)):
    global retriever

    subprocess.run(
        [sys.executable, "scripts/sync_faq_sheet.py"],
        check=True
    )

    retriever = RetrieverService()

    return {
        "status": "success",
        "message": "FAQ synced from Google Sheets and vector index rebuilt"
    }


@app.post("/admin/sync-rooms")
def sync_rooms(admin: bool = Depends(verify_admin)):
    subprocess.run(
        [sys.executable, "scripts/sync_rooms_sheet.py"],
        check=True
    )

    room_service.reload()

    return {
        "status": "success",
        "message": "Rooms synced from Google Sheets",
        "rooms_loaded": len(room_service.rooms),
        "available_rooms": len(room_service.available_rooms())
    }


@app.post("/admin/sync-all")
def sync_all(admin: bool = Depends(verify_admin)):
    global retriever

    subprocess.run(
        [sys.executable, "scripts/sync_faq_sheet.py"],
        check=True
    )

    subprocess.run(
        [sys.executable, "scripts/sync_rooms_sheet.py"],
        check=True
    )

    retriever = RetrieverService()
    room_service.reload()

    return {
        "status": "success",
        "message": "FAQ and rooms synced from Google Sheets",
        "rooms_loaded": len(room_service.rooms),
        "available_rooms": len(room_service.available_rooms())
    }

