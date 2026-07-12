# app/services/nlu_service.py

import json
import os
from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


class ChatIntent(str, Enum):
    ROOM_AVAILABILITY = "room_availability"
    ROOM_PRICE = "room_price"
    ROOM_COMPARISON = "room_comparison"
    FACILITY = "facility"
    RULES = "rules"
    LOCATION = "location"
    PAYMENT = "payment"
    CONTRACT = "contract"
    PHOTOS = "photos"
    FAQ = "faq"
    ADMIN_NEEDED = "admin_needed"
    SMALLTALK = "smalltalk"
    UNKNOWN = "unknown"


class ChatRoute(str, Enum):
    ROOM_INVENTORY = "room_inventory"
    FAQ_RAG = "faq_rag"
    ADMIN_FALLBACK = "admin_fallback"
    SMALLTALK = "smalltalk"


class Area(str, Enum):
    LIPPO = "lippo"
    JABABEKA = "jababeka"
    LEMBAH_HIJAU = "lembah_hijau"


class NLUResult(BaseModel):
    intent: ChatIntent = Field(default=ChatIntent.UNKNOWN)
    route: ChatRoute = Field(default=ChatRoute.FAQ_RAG)

    original_message: str
    clean_query: str

    area: Optional[Area] = None
    room_type_hint: Optional[str] = None
    budget_hint: Optional[int] = None

    move_in_date: Optional[date] = None
    wants_booking: bool = False
    wants_survey: bool = False
    gender_hint: Optional[Literal["putri", "putra", "any"]] = None

    is_follow_up: bool = False
    needs_admin: bool = False

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: Optional[str] = None


class NLUService:
    """
    LLM/NLU layer for Kost.cornerhouz.

    This service only understands the user's message.
    It does NOT generate final business answers.
    """

    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY")
        self.model = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
        self.enabled = bool(self.api_key)

    def analyze(
        self,
        user_message: str,
        last_user_message: Optional[str] = None,
        last_bot_message: Optional[str] = None,
        last_area: Optional[str] = None,
        conversation_history: Optional[list[dict[str, str]]] = None,
    ) -> NLUResult:
        if not user_message or not user_message.strip():
            return NLUResult(
                original_message=user_message or "",
                clean_query="",
                intent=ChatIntent.UNKNOWN,
                route=ChatRoute.ADMIN_FALLBACK,
                needs_admin=True,
                confidence=0.0,
                reason="Empty message",
            )

        if not self.enabled:
            return self._rule_based_fallback(user_message, last_area)

        try:
            return self._llm_analyze(
                user_message=user_message,
                last_user_message=last_user_message,
                last_bot_message=last_bot_message,
                last_area=last_area,
                conversation_history=conversation_history,
            )
        except Exception as exc:
            print(f"[NLU] LLM failed, using rule fallback: {exc}")
            return self._rule_based_fallback(user_message, last_area)

    def _llm_analyze(
        self,
        user_message: str,
        last_user_message: Optional[str],
        last_bot_message: Optional[str],
        last_area: Optional[str],
        conversation_history: Optional[list[dict[str, str]]],
    ) -> NLUResult:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        today = datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()

        recent_messages = self._prepare_recent_messages(
            conversation_history=conversation_history,
            last_user_message=last_user_message,
            last_bot_message=last_bot_message,
        )

        user_payload = {
            "current_date": today,
            "timezone": "Asia/Jakarta",
            "user_message": user_message,
            "conversation_context": {
                "recent_messages": recent_messages,
                "last_area": last_area,
            },
        }

        response = client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": self._build_system_prompt(),
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
        )

        raw_content = response.choices[0].message.content
        parsed = json.loads(raw_content)

        return self._validate_llm_result(parsed, user_message)

    def _build_system_prompt(self) -> str:
        return """
You are an NLU classifier for Kost.cornerhouz, an Indonesian kost/kostan FAQ chatbot.

Your job:
1. Detect the user's intent.
2. Rewrite messy/slang/typo Indonesian into a clean search query.
3. Normalize synonyms.
4. Extract area, budget, room type hints, move-in date, booking intent, survey intent, photo intent, and gender hints.
5. Decide which backend route should handle the message.

You are NOT allowed to answer the user.
You are NOT allowed to invent facts.
You are NOT allowed to create prices, room availability, deposits, addresses, facilities, rules, or admin policies.

The final chatbot answer will come only from:
- FAQ JSON
- room inventory JSON
- static backend responses
- admin fallback

Valid intents:
- room_availability
- room_price
- room_comparison
- facility
- rules
- location
- payment
- contract
- photos
- faq
- admin_needed
- smalltalk
- unknown

Valid routes:
- room_inventory
- faq_rag
- admin_fallback
- smalltalk

Valid areas:
- lippo
- jababeka
- lembah_hijau
- null

Area synonym mapping:
- lippo, meadow, meadow green, karawaci, dekat uph -> lippo
- jababeka, pavilion, cikarang, president university, presuniv -> jababeka
- lembah hijau, katalia, lippo cikarang, dekat sgc, pinus hijau -> lembah_hijau

Gender hint mapping:
- cewek, cewe, perempuan, wanita, putri, khusus putri -> putri
- cowok, laki-laki, pria, putra -> putra
- campur, bebas, siapa saja -> any
- if not mentioned -> null

Move-in date extraction:
- Extract move_in_date only if the user clearly mentions a planned move-in date.
- Return move_in_date in ISO format YYYY-MM-DD.
- If user says hari ini, besok, minggu depan, akhir bulan, infer based on current_date.
- If user says tanggal 15 and the month is not mentioned, infer the nearest upcoming date.
- If ambiguous, return null.
- Do not decide whether the date is acceptable. Backend will validate it.

Intent guidance:
- If user asks whether rooms are empty/available/kosong/ready/open -> room_availability and route room_inventory.
- If user asks price/harga/rate/sewa/berapa -> room_price.
- If user asks difference/beda/bedanya/compare -> room_comparison.
- If user asks for photos/pics/foto/gambar/Instagram/IG -> photos.
- If user asks rules such as pets, smoking, curfew, guests, pasangan -> rules.
- If user asks facilities such as AC, wifi, kitchen, laundry, kamar mandi -> facility.
- If user asks booking, survey, payment confirmation, WhatsApp admin, or negotiation -> admin_needed and route admin_fallback.
- If user says they want to book/pesan/keep/DP/survey/lihat kamar, set wants_booking or wants_survey true.
- If user only greets -> smalltalk.
- If unclear -> unknown.

Important:
- recent_messages contains the preceding chat bubbles in chronological order.
- Use recent_messages to resolve follow-ups such as "yang itu", "berapa harganya", or "ada wifi?".
- The current user_message takes priority over older context.
- Context helps interpret the request; it must never be used to invent property facts.
- For "ada kamar kosong?" without area, route must still be room_inventory, area must be null.
- For "lippo" after bot asked area, treat as follow-up room_availability with area lippo.
- For "bedanya apa?" after discussing an area, use last_area if available and mark is_follow_up true.
- For photos intent, do not describe photos. Backend will return Instagram link.
- clean_query should be a complete Indonesian question.
- Keep friendly Indonesian meaning, but do not answer.

Return ONLY valid JSON with this schema:
{
  "intent": "...",
  "route": "...",
  "original_message": "...",
  "clean_query": "...",
  "area": "lippo | jababeka | lembah_hijau | null",
  "room_type_hint": "string or null",
  "budget_hint": 1230000 or null",
  "move_in_date": "YYYY-MM-DD or null",
  "wants_booking": true or false,
  "wants_survey": true or false,
  "gender_hint": "putri | putra | any | null",
  "is_follow_up": true or false,
  "needs_admin": true or false,
  "confidence": 0.0,
  "reason": "short explanation"
}
"""

    def _prepare_recent_messages(
        self,
        conversation_history: Optional[list[dict[str, str]]],
        last_user_message: Optional[str],
        last_bot_message: Optional[str],
    ) -> list[dict[str, str]]:
        messages = conversation_history or []

        # Backward compatibility for callers that still provide only one turn.
        if not messages:
            if last_user_message:
                messages.append({"role": "user", "content": last_user_message})
            if last_bot_message:
                messages.append({"role": "assistant", "content": last_bot_message})

        prepared = []
        for message in messages[-4:]:
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            prepared.append({"role": role, "content": content[:1200]})

        return prepared

    def _validate_llm_result(self, parsed: dict, original_message: str) -> NLUResult:
        valid_intents = {item.value for item in ChatIntent}
        valid_routes = {item.value for item in ChatRoute}
        valid_areas = {item.value for item in Area}

        intent = parsed.get("intent", ChatIntent.UNKNOWN.value)
        route = parsed.get("route", ChatRoute.FAQ_RAG.value)
        area = parsed.get("area")

        if intent not in valid_intents:
            intent = ChatIntent.UNKNOWN.value

        if route not in valid_routes:
            route = ChatRoute.FAQ_RAG.value

        if area not in valid_areas:
            area = None

        raw_move_in_date = parsed.get("move_in_date")
        move_in_date = None

        if raw_move_in_date:
            try:
                move_in_date = date.fromisoformat(raw_move_in_date)
            except Exception:
                move_in_date = None

        gender_hint = parsed.get("gender_hint")
        if gender_hint not in {"putri", "putra", "any"}:
            gender_hint = None

        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0.0

        confidence = max(0.0, min(confidence, 1.0))

        return NLUResult(
            intent=intent,
            route=route,
            original_message=original_message,
            clean_query=parsed.get("clean_query") or original_message,
            area=area,
            room_type_hint=parsed.get("room_type_hint"),
            budget_hint=parsed.get("budget_hint"),
            move_in_date=move_in_date,
            wants_booking=bool(parsed.get("wants_booking", False)),
            wants_survey=bool(parsed.get("wants_survey", False)),
            gender_hint=gender_hint,
            is_follow_up=bool(parsed.get("is_follow_up", False)),
            needs_admin=bool(parsed.get("needs_admin", False)),
            confidence=confidence,
            reason=parsed.get("reason"),
        )

    def _rule_based_fallback(
        self,
        user_message: str,
        last_area: Optional[str] = None,
    ) -> NLUResult:
        text = user_message.lower().strip()
        area = self._detect_area(text)

        photo_keywords = [
            "foto",
            "photo",
            "photos",
            "pic",
            "pics",
            "gambar",
            "ig",
            "instagram",
            "lihat foto",
            "liat foto",
        ]

        booking_keywords = [
            "booking",
            "book",
            "pesan",
            "keep",
            "dp",
            "jadi ambil",
            "mau ambil",
            "mau masuk",
            "pindah",
        ]

        survey_keywords = [
            "survey",
            "lihat kamar",
            "liat kamar",
            "cek kamar",
            "datang lihat",
            "boleh lihat",
        ]

        availability_keywords = [
            "kosong",
            "available",
            "avail",
            "ready",
            "ada kamar",
            "kamar ada",
            "masih ada",
            "tersedia",
        ]

        price_keywords = [
            "harga",
            "berapa",
            "sewa",
            "rate",
            "deposit",
            "dp",
        ]

        comparison_keywords = [
            "beda",
            "bedanya",
            "perbedaan",
            "compare",
            "banding",
            "mana yang",
        ]

        if any(keyword in text for keyword in photo_keywords):
            return NLUResult(
                original_message=user_message,
                clean_query="Di mana saya bisa melihat foto kamar kost?",
                intent=ChatIntent.PHOTOS,
                route=ChatRoute.FAQ_RAG,
                area=area,
                confidence=0.9,
                reason="Rule-based photo keyword match",
            )

        if any(keyword in text for keyword in booking_keywords):
            return NLUResult(
                original_message=user_message,
                clean_query=user_message,
                intent=ChatIntent.ADMIN_NEEDED,
                route=ChatRoute.ADMIN_FALLBACK,
                area=area,
                wants_booking=True,
                needs_admin=True,
                confidence=0.75,
                reason="Rule-based booking keyword match",
            )

        if any(keyword in text for keyword in survey_keywords):
            return NLUResult(
                original_message=user_message,
                clean_query=user_message,
                intent=ChatIntent.ADMIN_NEEDED,
                route=ChatRoute.ADMIN_FALLBACK,
                area=area,
                wants_survey=True,
                needs_admin=True,
                confidence=0.75,
                reason="Rule-based survey keyword match",
            )

        if any(keyword in text for keyword in availability_keywords):
            normalized_area = area or last_area
            return NLUResult(
                original_message=user_message,
                clean_query=self._build_clean_room_query(normalized_area, "availability"),
                intent=ChatIntent.ROOM_AVAILABILITY,
                route=ChatRoute.ROOM_INVENTORY,
                area=normalized_area,
                is_follow_up=bool(last_area and not area),
                confidence=0.8,
                reason="Rule-based availability keyword match",
            )

        if area and len(text.split()) <= 4:
            return NLUResult(
                original_message=user_message,
                clean_query=self._build_clean_room_query(area, "availability"),
                intent=ChatIntent.ROOM_AVAILABILITY,
                route=ChatRoute.ROOM_INVENTORY,
                area=area,
                is_follow_up=True,
                confidence=0.75,
                reason="Short area-only follow-up",
            )

        if any(keyword in text for keyword in comparison_keywords):
            normalized_area = area or last_area
            return NLUResult(
                original_message=user_message,
                clean_query=self._build_clean_room_query(normalized_area, "comparison"),
                intent=ChatIntent.ROOM_COMPARISON,
                route=ChatRoute.ROOM_INVENTORY,
                area=normalized_area,
                is_follow_up=bool(last_area and not area),
                confidence=0.75,
                reason="Rule-based comparison keyword match",
            )

        if any(keyword in text for keyword in price_keywords):
            normalized_area = area or last_area
            return NLUResult(
                original_message=user_message,
                clean_query=self._build_clean_room_query(normalized_area, "price"),
                intent=ChatIntent.ROOM_PRICE,
                route=(
                    ChatRoute.ROOM_INVENTORY
                    if normalized_area
                    else ChatRoute.FAQ_RAG
                ),
                area=normalized_area,
                is_follow_up=bool(last_area and not area),
                confidence=0.7,
                reason="Rule-based price keyword match",
            )

        if text in {"halo", "hai", "hi", "hello", "pagi", "siang", "sore", "malam"}:
            return NLUResult(
                original_message=user_message,
                clean_query=user_message,
                intent=ChatIntent.SMALLTALK,
                route=ChatRoute.SMALLTALK,
                confidence=0.9,
                reason="Greeting detected",
            )

        return NLUResult(
            original_message=user_message,
            clean_query=user_message,
            intent=ChatIntent.FAQ,
            route=ChatRoute.FAQ_RAG,
            confidence=0.45,
            reason="Default fallback to FAQ RAG",
        )

    def _detect_area(self, text: str) -> Optional[Area]:
        lippo_keywords = [
            "lippo",
            "meadow",
            "meadow green",
            "karawaci",
            "uph",
        ]

        jababeka_keywords = [
            "jababeka",
            "pavilion",
            "cikarang",
            "president university",
            "presuniv",
            "president uni",
        ]

        lembah_keywords = [
            "lembah hijau",
            "lembah",
            "katalia",
            "sgc",
            "lippo cikarang",
            "pinus hijau",
        ]

        if any(keyword in text for keyword in lippo_keywords):
            return Area.LIPPO

        if any(keyword in text for keyword in jababeka_keywords):
            return Area.JABABEKA

        if any(keyword in text for keyword in lembah_keywords):
            return Area.LEMBAH_HIJAU

        return None

    def _build_clean_room_query(
        self,
        area: Optional[str],
        query_type: Literal["availability", "price", "comparison"],
    ) -> str:
        area_text = {
            Area.LIPPO: "Lippo atau Meadow Green",
            Area.JABABEKA: "Jababeka atau Pavilion",
            Area.LEMBAH_HIJAU: "Lembah Hijau atau Katalia",
            "lippo": "Lippo atau Meadow Green",
            "jababeka": "Jababeka atau Pavilion",
            "lembah_hijau": "Lembah Hijau atau Katalia",
            None: "",
        }.get(area, "")

        if query_type == "availability":
            if area_text:
                return f"Apakah ada kamar kosong di area {area_text}?"
            return "Apakah ada kamar kosong?"

        if query_type == "price":
            if area_text:
                return f"Berapa harga kamar di area {area_text}?"
            return "Berapa harga kamar kost?"

        if query_type == "comparison":
            if area_text:
                return f"Apa perbedaan tipe kamar di area {area_text}?"
            return "Apa perbedaan tipe kamar yang tersedia?"

        return ""
