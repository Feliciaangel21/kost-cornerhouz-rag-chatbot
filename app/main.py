import os
import subprocess
import sys
import re
import threading
import time

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import quote

from app.services.retriever_service import RetrieverService
from app.services.confidence_service import decide_action
from app.services.template_reply_service import generate_template_reply
from app.services.room_inventory_service import RoomInventoryService
from app.services.chat_logger_service import log_chat, read_logs
from app.services.nlu_service import NLUService, ChatIntent, ChatRoute
from app.services.move_in_gate_service import MoveInGateService, MoveInGateStatus

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
nlu_service = NLUService()
move_in_gate_service = MoveInGateService(max_keep_days=15)

session_state = {}
CONVERSATION_HISTORY_LIMIT = 4
sync_lock = threading.Lock()
last_public_sync_at = 0.0
last_public_sync_result = None
SYNC_ON_REFRESH_MIN_SECONDS = int(os.getenv("SYNC_ON_REFRESH_MIN_SECONDS", "60"))


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    conversation_history: list[dict[str, str]] | None = None


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

def is_area_answer(message: str) -> bool:
    q = message.lower().strip()

    area_keywords = [
        "lippo",
        "meadow",
        "meadow green",
        "karawaci",
        "uph",
        "jababeka",
        "pavilion",
        "president",
        "presuniv",
        "lembah",
        "lembah hijau",
        "katalia",
    ]

    return any(keyword in q for keyword in area_keywords)

def detect_area_value(message: str) -> str | None:
    q = message.lower().strip()

    # Keep the more specific Cikarang/Lembah phrase before the broad Lippo
    # keywords so "Lippo Cikarang" does not get remembered as Meadow Green.
    area_keywords = [
        (
            "lembah_hijau",
            [
                "lembah hijau",
                "lembah",
                "katalia",
                "sgc",
                "lippo cikarang",
                "pinus hijau",
            ],
        ),
        (
            "jababeka",
            [
                "jababeka",
                "pavilion",
                "cikarang",
                "president university",
                "presuniv",
                "president uni",
            ],
        ),
        (
            "lippo",
            [
                "lippo",
                "meadow",
                "meadow green",
                "karawaci",
                "uph",
            ],
        ),
    ]

    for area, keywords in area_keywords:
        if any(keyword in q for keyword in keywords):
            return area

    return None

def is_facility_or_rule_question(message: str) -> bool:
    q = message.lower().strip()

    keywords = [
        "parkir",
        "motor",
        "mobil",
        "wifi",
        "dapur",
        "laundry",
        "mesin cuci",
        "gas",
        "masak",
        "kompor",
        "ac",
        "water heater",
        "tamu",
        "pacar",
        "lawan jenis",
        "teman",
        "ortu",
        "orang tua",
        "menginap",
        "nginep",
        "jam malam",
        "jam bertamu",
        "hewan",
        "binatang",
        "peliharaan",
        "rokok",
        "merokok",
        "aturan",
        "peraturan",
        "tata tertib",
        "denda",
        "telat bayar",
        "check out",
        "checkout",
    ]

    return any(keyword in q for keyword in keywords)

def is_kost_bebas_question(message: str) -> bool:
    q = message.lower().strip()
    keywords = [
        "kost bebas",
        "kos bebas",
        "texas",
        "vegas",
        "bawa pasangan",
        "bawa pacar",
    ]

    return any(keyword in q for keyword in keywords)

def build_kost_bebas_reply() -> str:
    return (
        "Bukan kost bebas ya kak. Di semua lokasi Kost.cornerhouz, pasangan "
        "atau lawan jenis tidak boleh masuk kamar dan tidak boleh menginap.\n\n"
        "Tamu hanya boleh bertamu di ruang tamu/area tamu sampai maksimal "
        "pukul 21.00."
    )

def is_admin_forward_request(message: str) -> bool:
    q = message.lower().strip()

    admin_phrase_keywords = [
        "booking",
        "book",
        "pesan",
        "keep",
        "survey",
        "lihat kamar",
        "liat kamar",
        "cek kamar",
        "datang lihat",
        "boleh lihat",
        "mau ambil",
        "jadi ambil",
        "mau masuk",
        "pindah",
        "nego",
        "admin",
        "whatsapp",
    ]

    admin_token_keywords = [
        "dp",
        "wa",
    ]

    return (
        any(keyword in q for keyword in admin_phrase_keywords)
        or any(
            re.search(rf"\b{re.escape(keyword)}\b", q)
            for keyword in admin_token_keywords
        )
    )

def is_move_in_date_like(message: str) -> bool:
    q = message.lower().strip()

    date_keywords = [
        "hari ini",
        "besok",
        "lusa",
        "minggu depan",
        "bulan depan",
        "bln depan",
        "bulan dpn",
        "tanggal",
        "tgl",
        "check in",
        "check-in",
        "masuk",
        "januari",
        "jan",
        "februari",
        "feb",
        "maret",
        "mar",
        "april",
        "apr",
        "mei",
        "juni",
        "jun",
        "juli",
        "jul",
        "agustus",
        "agus",
        "september",
        "sep",
        "oktober",
        "okt",
        "november",
        "nov",
        "desember",
        "des",
    ]
    if any(keyword in q for keyword in date_keywords):
        return True

    # Examples: 7/7, 07-07, 7 7
    if re.search(r"\b\d{1,2}\s*[\/\-\s]\s*\d{1,2}\b", q):
        return True

    # When the bot has just asked for a move-in date, users often answer with
    # only the day number, e.g. "15".
    if re.fullmatch(r"\d{1,2}", q):
        day = int(q)
        return 1 <= day <= 31

    return False

def is_booking_confirmation(message: str) -> bool:
    q = message.lower().strip()
    match_q = re.sub(r"(.)\1{2,}", r"\1\1", q)

    finished_questions_phrases = [
        "tidak ada pertanyaan lanjut",
        "gak ada pertanyaan lanjut",
        "ga ada pertanyaan lanjut",
    ]
    if any(phrase in match_q for phrase in finished_questions_phrases):
        return True

    # Do not expose the owner's number when a positive phrase is negated,
    # for example "belum mau lanjut booking".
    negated_confirmation = re.search(
        r"\b(tidak|nggak|gak|ga|belum|jangan|batal)\b.{0,35}"
        r"\b(lanjut|booking|book|survey)\b",
        match_q,
    )
    if negated_confirmation:
        return False

    confirmation_phrases = [
        "booking",
        "book",
        "survey",
        "lanjut",
        "lanjut booking",
        "lanjut ke booking",
        "proceed booking",
        "proceed with booking",
        "lanjut survey",
        "lanjut ke survey",
        "mau lanjut survey",
        "ingin lanjut survey",
        "siap survey",
        "mau lanjut booking",
        "ingin lanjut booking",
        "jadi booking",
        "jadi book",
        "siap booking",
        "oke booking",
        "ok booking",
        "ya booking",
        "iya booking",
        "sudah jelas lanjut",
        "udah jelas lanjut",
    ]

    return any(phrase in match_q for phrase in confirmation_phrases)

def prepare_conversation_history(
    history: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    prepared = []
    for item in history or []:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        prepared.append({"role": role, "content": content[:1200]})

    return prepared[-CONVERSATION_HISTORY_LIMIT:]

def history_is_waiting_for_booking_confirmation(
    history: list[dict[str, str]],
) -> bool:
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue

        content = item.get("content", "").lower()
        if "wa.me/" in content or "owner lewat link" in content:
            return False

        return (
            "sebelum booking" in content
            and (
                "lanjut booking" in content
                or "lanjut survey" in content
            )
        )

    return False

def infer_last_area_from_history(history: list[dict[str, str]]) -> str | None:
    for item in reversed(history):
        content = item.get("content", "")
        area = detect_area_value(content)
        if area:
            return area

    return None

def infer_move_in_date_from_history(history: list[dict[str, str]]):
    for item in reversed(history):
        if item.get("role") != "user":
            continue

        content = item.get("content", "")
        if not is_move_in_date_like(content):
            continue

        result = move_in_gate_service.check(
            requires_admin_forward=True,
            move_in_date=None,
            user_message=content,
        )
        if result.parsed_move_in_date:
            return result.parsed_move_in_date

    return None

def infer_handoff_type_from_history(history: list[dict[str, str]]) -> str:
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue

        content = item.get("content", "").lower()
        if "lanjut survey" in content:
            return "survey"

        if "lanjut booking" in content:
            return "booking"

    return "booking"

def build_difference_reply() -> str:
    return (
        "Bedanya biasanya dari tipe kamar dan posisi jendela, kak. "
        "Kamar mandi dalam lebih mahal karena kamar mandinya private dan ada water heater. "
        "Untuk kamar mandi luar, kalau harganya di atas Rp1.000.000 berarti jendela depan, "
        "jadi lebih mahal dibanding kamar mandi luar biasa/jendela lorong. "
        "Kakak lebih cari yang budget 1 jutaan atau yang jendela depan?"
    )

def build_kost_rules_text() -> str:
    return (
        "Tata tertib kost:\n"
        "1. Penghuni wajib menjaga ketertiban, kebersihan, dan kenyamanan bersama.\n"
        "2. Tamu lawan jenis dilarang masuk kamar atau menginap.\n"
        "3. Tamu hanya diperbolehkan bertamu sampai maksimal pukul 21.00 dan hanya di ruang tamu/area tamu.\n"
        "4. Tamu yang menginap wajib konfirmasi terlebih dahulu ke admin/owner. Biaya tamu menginap Rp100.000 per hari. Tamu lawan jenis tetap tidak diperbolehkan menginap.\n"
        "5. Penghuni dilarang membawa binatang peliharaan.\n"
        "6. Kerusakan atau kehilangan properti kost dapat dipotong dari deposit.\n"
        "7. Penghuni dilarang berkelahi, membuat gaduh, atau mengganggu kenyamanan penghuni lain.\n"
        "8. Dilarang menyetrika di atas kasur karena dapat merusak kasur. Kerusakan dapat dipotong dari deposit.\n"
        "9. Dilarang memaku pintu atau tembok. Gunakan gantungan berperekat jika ingin memasang gantungan.\n"
        "10. Dilarang merokok di dalam kamar dan area umum. Merokok hanya diperbolehkan di luar rumah atau balkon.\n"
        "11. Dilarang parkir di depan rumah tetangga. Kerusakan atau masalah akibat parkir sembarangan bukan tanggung jawab kost.\n"
        "12. Dilarang meletakkan barang pribadi di luar kamar. Barang di luar kamar dapat dipindahkan demi kenyamanan bersama.\n"
        "13. Peralatan makan dan masak wajib dicuci sendiri setelah digunakan.\n"
        "14. Dilarang menggunakan mesin cuci milik kost.\n"
        "15. Jatah gas adalah 1 tabung per bulan dan hanya untuk memasak ringan seperti Indomie atau telur. Dilarang memasak berat atau masakan berbau menyengat.\n"
        "16. Jika ada kebocoran air pada closet, shower, wastafel, atau fasilitas lain, penghuni wajib segera melapor. Jika lalai dan menyebabkan tagihan air melonjak, biaya kelebihan dapat dibebankan kepada penghuni.\n"
        "17. Keterlambatan pembayaran sewa kost dikenakan denda Rp50.000 per hari.\n"
        "18. Jika tidak memperpanjang sewa kost, penghuni wajib memberi info minimal 1 bulan sebelumnya.\n"
        "19. Check-out maksimal pukul 12.00 siang. Lewat dari pukul 12.00 dianggap extend dan dikenakan charge Rp100.000 per hari."
    )

def build_unknown_reply() -> str:
    return (
        "Maaf kak, untuk info itu aku belum punya data yang pasti 🙏\n\n"
        "Kakak bisa tanya soal:\n"
        "• ketersediaan kamar\n"
        "• harga dan deposit\n"
        "• lokasi kost\n"
        "• fasilitas\n"
        "• aturan kost\n"
        "• booking atau survey\n\n"
        "Kalau mau, kakak bisa tulis pertanyaannya lebih spesifik ya."
    )

def build_faq_response(
    search_query: str,
    user_message: str,
    reason: str = "Answered using FAQ RAG",
) -> ChatResponse:
    results = retriever.search(search_query, top_k=5)
    decision = decide_action(results, search_query)

    top_faq = results[0]["faq"] if results else None
    matched_faq_ids = [result["faq"]["id"] for result in results]

    if not results or decision["confidence"] < 0.55:
        return ChatResponse(
            reply=build_unknown_reply(),
            confidence=decision["confidence"],
            action="UNKNOWN_NOT_IN_KB",
            reason="No confident FAQ match found",
            matched_faq_ids=matched_faq_ids,
            needs_admin=False,
            source="faq_rag"
        )

    reply = generate_template_reply(
        action=decision["action"],
        faq=top_faq,
        user_message=user_message
    )

    needs_admin = decision["action"] in [
        "ESCALATE",
        "ESCALATE_WITH_CONTEXT"
    ]

    return ChatResponse(
        reply=reply,
        confidence=decision["confidence"],
        action=decision["action"],
        reason=reason or decision["reason"],
        matched_faq_ids=matched_faq_ids,
        needs_admin=needs_admin,
        source="faq_rag"
    )

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

def format_rupiah_simple(amount: int) -> str:
    return "Rp" + f"{amount:,}".replace(",", ".")


def build_booking_review_reply(handoff_type: str = "booking") -> str:
    dp_amount = int(os.getenv("BOOKING_DP_AMOUNT", "500000"))

    if handoff_type == "survey":
        title = "Tanggalnya masih dalam waktu dekat, jadi rencana survey bisa dilanjutkan ya kak."
        proceed_prompt = "Kalau sudah jelas dan ingin lanjut survey, tulis 'lanjut survey' ya kak."
    else:
        title = "Tanggal masuknya masih dalam waktu dekat, jadi proses booking bisa dilanjutkan ya kak."
        proceed_prompt = "Kalau sudah jelas dan ingin lanjut, tulis 'lanjut booking' ya kak."

    booking_deposit_text = (
        "Info DP/deposit:\n"
        f"• Untuk keep kamar, perlu membayar DP/deposit sebesar {format_rupiah_simple(dp_amount)}.\n"
        "• DP/deposit digunakan untuk mengunci kamar agar tidak diberikan ke calon penghuni lain.\n"
        "• Saat mulai masuk, DP tersebut akan menjadi deposit/jaminan kost.\n"
        "• DP/deposit tidak memotong biaya sewa bulan pertama.\n"
        "• Saat check-in, kakak tetap membayar sewa bulan pertama sesuai harga kamar yang dipilih.\n"
        "• Ketersediaan kamar bisa berubah sebelum DP/deposit dikonfirmasi.\n\n"
        "Contoh:\n"
        "Jika harga kamar Rp1.500.000/bulan:\n"
        f"• DP/deposit untuk keep kamar: {format_rupiah_simple(dp_amount)}\n"
        "• Dibayar saat masuk: Rp1.500.000\n"
        "• Total pembayaran awal: Rp2.000.000\n\n"
    )

    return (
        f"{title}\n\n"
        "Sebelum booking, mohon dibaca dulu ya kak:\n\n"
        + booking_deposit_text
        + build_kost_rules_text()
        + "\n\nAda pertanyaan lain tentang kamar, fasilitas, biaya, atau peraturannya? "
        + proceed_prompt
    )


def build_owner_whatsapp_reply(
    user_message: str,
    last_area: str | None = None,
    move_in_date=None,
    handoff_type: str = "booking",
) -> str:
    owner_number = os.getenv("OWNER_WHATSAPP_NUMBER", "").strip()

    area_text = last_area or "belum disebutkan"
    date_text = str(move_in_date) if move_in_date else "belum disebutkan"

    if handoff_type == "survey":
        wa_intent = "Saya sudah membaca peraturan dan ingin lanjut survey kamar"
    else:
        wa_intent = "Saya sudah membaca peraturan dan ingin lanjut booking kamar"

    if not owner_number:
        return "Nomor owner belum diset di sistem. Kakak bisa tunggu admin menghubungi ya 🙏"

    wa_message = (
        f"Halo, {wa_intent}.\n"
        f"Area: {area_text}\n"
        f"Tanggal masuk: {date_text}\n"
        f"Pertanyaan awal: {user_message}"
    )

    wa_link = f"https://wa.me/{owner_number}?text={quote(wa_message)}"

    return f"Siap kak. Untuk menyelesaikan prosesnya, silakan chat owner lewat link ini:\n{wa_link}"

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


def sync_google_sheets_data() -> dict:
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
        "message": "FAQ and rooms synced from Google Sheets",
        "rooms_loaded": len(room_service.rooms),
        "available_rooms": len(room_service.available_rooms())
    }


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
    client_history = prepare_conversation_history(request.conversation_history)

    awaiting_room_location = state.get("awaiting_room_location", False)
    awaiting_move_in_date = state.get("awaiting_move_in_date", False)
    awaiting_booking_confirmation = state.get("awaiting_booking_confirmation", False)
    pending_booking = state.get("pending_booking")
    last_area = state.get("last_area")
    last_user_message = state.get("last_user_message")
    last_bot_message = state.get("last_bot_message")
    conversation_history = state.get("conversation_history") or client_history

    user_message = request.message

    if not last_area:
        last_area = infer_last_area_from_history(conversation_history)

    if (
        not awaiting_booking_confirmation
        and history_is_waiting_for_booking_confirmation(conversation_history)
    ):
        parsed_date = infer_move_in_date_from_history(conversation_history)
        awaiting_booking_confirmation = True
        pending_booking = pending_booking or {
            "initial_message": user_message,
            "area": last_area,
            "move_in_date": str(parsed_date) if parsed_date else None,
            "handoff_type": infer_handoff_type_from_history(conversation_history),
        }

    # 0. NLU layer: understand messy/slang/typo user message
    nlu = nlu_service.analyze(
        user_message=user_message,
        last_user_message=last_user_message,
        last_bot_message=last_bot_message,
        last_area=last_area,
        conversation_history=conversation_history,
    )

    print("[NLU]", nlu.model_dump())

    detected_area = detect_area_value(user_message)
    if nlu.area:
        last_area = nlu.area.value
    elif detected_area:
        last_area = detected_area

    area_answer = bool(detected_area) or bool(nlu.area)
    facility_or_rule_question = (
        is_facility_or_rule_question(user_message)
        or nlu.intent in {
            ChatIntent.FACILITY,
            ChatIntent.RULES,
            ChatIntent.PAYMENT,
            ChatIntent.CONTRACT,
        }
    )

    print("[ROUTING]", {
        "awaiting_room_location": awaiting_room_location,
        "is_area_answer": area_answer,
        "is_facility_or_rule": facility_or_rule_question,
        "intent": nlu.intent,
        "route": nlu.route,
    })

    # Helper to save state + logs consistently
    def finalize_response(response: ChatResponse):
        updated_history = [
            *conversation_history,
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response.reply},
        ][-CONVERSATION_HISTORY_LIMIT:]

        session_state[session_id] = {
            "awaiting_room_location": response.action == "ROOM_LOOKUP_ASK_LOCATION",
            "awaiting_move_in_date": (
                response.action == "MOVE_IN_DATE_REQUIRED"
                or "Rencana masuknya kapan" in response.reply
                or "Rencana masuknya kapan ya kak" in response.reply
                or "Rencana mulai masuk tanggal berapa" in response.reply
            ),
            "awaiting_booking_confirmation": awaiting_booking_confirmation,
            "pending_booking": pending_booking,
            "last_area": last_area,
            "last_user_message": user_message,
            "last_bot_message": response.reply,
            "conversation_history": updated_history,
        }

        log_chat({
            "session_id": session_id,
            "user_message": user_message,
            "bot_reply": response.reply,
            "source": response.source,
            "action": response.action,
            "confidence": response.confidence,
            "needs_admin": response.needs_admin,
            "matched_faq_ids": response.matched_faq_ids,
        })

        return response

    # 1. Photo / Instagram handling
    if nlu.intent == ChatIntent.PHOTOS:
        instagram_url = os.getenv(
            "INSTAGRAM_URL",
            "https://www.instagram.com/kost.cornerhouz/"
        )

        response = ChatResponse(
            reply=(
                "Untuk foto-foto kamar dan kost, kakak bisa cek Instagram kami di sini ya:\n"
                f"[Instagram Kost.cornerhouz]({instagram_url})"
            ),
            confidence=1.0,
            action="STATIC_INSTAGRAM_LINK",
            reason="User asked for room/kost photos",
            matched_faq_ids=[],
            needs_admin=False,
            source="static"
        )

        return finalize_response(response)

    if is_kost_bebas_question(user_message):
        response = ChatResponse(
            reply=build_kost_bebas_reply(),
            confidence=1.0,
            action="STATIC_KOST_BEBAS_RULE",
            reason="Answered kost bebas/Texas/Vegas partner rule",
            matched_faq_ids=["FAQ_RULES_001"],
            needs_admin=False,
            source="static"
        )

        return finalize_response(response)

    # 2. WhatsApp is only revealed after the user explicitly confirms they
    # have finished asking questions and want to proceed.
    if awaiting_booking_confirmation and is_booking_confirmation(user_message):
        booking_context = pending_booking or {}
        response = ChatResponse(
            reply=build_owner_whatsapp_reply(
                user_message=booking_context.get("initial_message", user_message),
                last_area=booking_context.get("area") or last_area,
                move_in_date=booking_context.get("move_in_date"),
                handoff_type=booking_context.get("handoff_type", "booking"),
            ),
            confidence=1.0,
            action="OWNER_WHATSAPP_LINK",
            reason="User explicitly confirmed they want to proceed with booking",
            matched_faq_ids=[],
            needs_admin=True,
            source="booking_confirmation"
        )
        awaiting_booking_confirmation = False
        pending_booking = None

        return finalize_response(response)

    message_is_move_in_answer = (
        awaiting_move_in_date
        and is_move_in_date_like(user_message)
    )

    # 3. Move-in gate before room inventory / admin fallback / booking / survey
    explicit_admin_request = (
        is_admin_forward_request(user_message)
        or nlu.wants_booking
        or nlu.wants_survey
    )

    requires_admin_forward = (
        not awaiting_booking_confirmation
        and (message_is_move_in_answer or explicit_admin_request)
    )
    gate_result = move_in_gate_service.check(
        requires_admin_forward=requires_admin_forward,
        move_in_date=nlu.move_in_date,
        user_message=user_message,
    )

    if gate_result.status == MoveInGateStatus.NEED_DATE:
        response = ChatResponse(
            reply=gate_result.message,
            confidence=1.0,
            action="MOVE_IN_DATE_REQUIRED",
            reason="Admin forwarding requires move-in date",
            matched_faq_ids=[],
            needs_admin=False,
            source="move_in_gate"
        )

        return finalize_response(response)

    if gate_result.status == MoveInGateStatus.TOO_FAR:
        response = ChatResponse(
            reply=gate_result.message,
            confidence=1.0,
            action="MOVE_IN_DATE_TOO_FAR",
            reason="Move-in date is more than 15 days away",
            matched_faq_ids=[],
            needs_admin=False,
            source="move_in_gate"
        )

        return finalize_response(response)

    if gate_result.status == MoveInGateStatus.PAST_DATE:
        response = ChatResponse(
            reply=gate_result.message,
            confidence=1.0,
            action="MOVE_IN_DATE_PAST",
            reason="Move-in date is in the past",
            matched_faq_ids=[],
            needs_admin=False,
            source="move_in_gate"
        )

        return finalize_response(response)

    if gate_result.status == MoveInGateStatus.ALLOWED:
        q = user_message.lower()

        handoff_type = "booking"
        if nlu.wants_survey or "survey" in q or "lihat kamar" in q or "liat kamar" in q:
            handoff_type = "survey"

        parsed_date = getattr(gate_result, "parsed_move_in_date", None) or nlu.move_in_date

        pending_booking = {
            "initial_message": user_message,
            "area": last_area,
            "move_in_date": str(parsed_date) if parsed_date else None,
            "handoff_type": handoff_type,
        }
        awaiting_booking_confirmation = True

        response = ChatResponse(
            reply=build_booking_review_reply(handoff_type=handoff_type),
            confidence=1.0,
            action="BOOKING_REVIEW_REQUIRED",
            reason="Move-in date is valid; waiting for explicit booking confirmation",
            matched_faq_ids=[],
            needs_admin=False,
            source="move_in_gate"
        )

        return finalize_response(response)

    # 3. Smalltalk
    if nlu.intent == ChatIntent.SMALLTALK:
        response = ChatResponse(
            reply=(
                "Halo kak 👋 Ada yang bisa kami bantu? "
                "Kakak mau tanya ketersediaan kamar, harga, fasilitas, atau lokasi kost?"
            ),
            confidence=1.0,
            action="SMALLTALK",
            reason="Greeting or smalltalk detected",
            matched_faq_ids=[],
            needs_admin=False,
            source="static"
        )

        return finalize_response(response)

    # 4. Facility/rule questions should not be hijacked by stale room state.
    if facility_or_rule_question:
        search_query = nlu.clean_query or user_message
        response = build_faq_response(
            search_query=search_query,
            user_message=user_message,
            reason="Answered facility/rule question using FAQ RAG",
        )

        return finalize_response(response)

    # 3. Follow-up question about price/type difference
    # Keep your existing hardcoded safe answer.
    if (
        is_difference_question(user_message)
        or nlu.intent == ChatIntent.ROOM_COMPARISON
    ):
        response = ChatResponse(
            reply=build_difference_reply(),
            confidence=1.0,
            action="FOLLOWUP_DIFFERENCE",
            reason="Answered price/type difference follow-up",
            matched_faq_ids=[],
            needs_admin=False,
            source="room_inventory"
        )

        return finalize_response(response)

    # 4. Room availability / structured inventory route
    should_use_room_inventory = (
        nlu.route == ChatRoute.ROOM_INVENTORY
        or room_service.is_room_query(user_message)
        or (
            awaiting_room_location
            and area_answer
        )
    )

    if should_use_room_inventory:
        room_query = nlu.clean_query or user_message

        room_answer = room_service.answer_room_query(
            room_query,
            allow_followup_question=not (awaiting_room_location and area_answer)
        )

        action = "ROOM_LOOKUP"
        if room_answer.get("followup_needed"):
            action = "ROOM_LOOKUP_ASK_LOCATION"

        response = ChatResponse(
            reply=room_answer["reply"],
            confidence=1.0,
            action=action,
            reason="Answered using structured room inventory",
            matched_faq_ids=[],
            needs_admin=room_answer.get("needs_admin", False),
            source="room_inventory"
        )

        return finalize_response(response)

    # 6. General FAQ RAG questions
    # Use clean_query so typo/slang/synonym input gets better retrieval.
    search_query = nlu.clean_query or user_message
    response = build_faq_response(
        search_query=search_query,
        user_message=user_message,
    )

    return finalize_response(response)


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
    result = sync_google_sheets_data()

    return {
        "status": "success",
        **result
    }


@app.post("/sync-on-refresh")
def sync_on_refresh():
    global last_public_sync_at, last_public_sync_result

    now = time.time()
    if (
        last_public_sync_result
        and SYNC_ON_REFRESH_MIN_SECONDS > 0
        and now - last_public_sync_at < SYNC_ON_REFRESH_MIN_SECONDS
    ):
        return {
            "status": "skipped_recent",
            **last_public_sync_result
        }

    if not sync_lock.acquire(blocking=False):
        return {
            "status": "already_running",
            "message": "Google Sheets sync is already running"
        }

    try:
        result = sync_google_sheets_data()
        last_public_sync_at = time.time()
        last_public_sync_result = result

        return {
            "status": "success",
            **result
        }
    finally:
        sync_lock.release()
