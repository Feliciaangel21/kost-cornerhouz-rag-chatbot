import json
import re
from pathlib import Path


ROOM_DATA_PATH = Path("data/room_inventory_public_clean.json")


def normalize_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def format_rupiah(value) -> str:
    try:
        value = int(float(value))
        return f"Rp{value:,.0f}".replace(",", ".")
    except Exception:
        return "harga belum tersedia"


def human_join(items: list[str]) -> str:
    items = [item for item in items if item]

    if not items:
        return ""

    if len(items) == 1:
        return items[0]

    if len(items) == 2:
        return f"{items[0]} dan {items[1]}"

    return ", ".join(items[:-1]) + f", dan {items[-1]}"


def parse_price_query(message: str):
    q = normalize_text(message)

    if "1 5" in q or "1 500" in q or "1500000" in q or "1 5 juta" in q:
        return 1500000

    if "1 juta" in q or "1000000" in q or "1jt" in q or "1 jt" in q:
        return 1000000

    if "1 3" in q or "1300000" in q or "1 3 juta" in q:
        return 1300000

    if "1 2" in q or "1200000" in q or "1 2 juta" in q:
        return 1200000

    return None


def detect_bathroom_type(message: str):
    q = normalize_text(message)

    if "kamar mandi dalam" in q or "km dalam" in q or "dalam" in q:
        return "kamar mandi dalam"

    if "kamar mandi luar" in q or "km luar" in q or "luar" in q:
        return "kamar mandi luar"

    return None


def detect_areas(message: str):
    q = normalize_text(message)

    areas = []

    if any(word in q for word in ["lippo", "meadow", "meadow green"]):
        areas.append("Meadow Green")

    if any(word in q for word in ["jababeka", "pavilion"]):
        areas.append("Jababeka")

    if any(word in q for word in ["lembah", "lembah hijau", "katalia"]):
        areas.append("Lembah Hijau")

    unique = []
    for area in areas:
        if area not in unique:
            unique.append(area)

    return unique


def is_vague_room_message(message: str) -> bool:
    q = normalize_text(message)

    vague_messages = [
        "kamar",
        "room",
        "kost",
        "kos",
        "info kamar",
        "mau tanya kamar",
        "tanya kamar"
    ]

    return q in vague_messages


class RoomInventoryService:
    def __init__(self):
        self.rooms = self.load_rooms()

    def load_rooms(self):
        if not ROOM_DATA_PATH.exists():
            print(f"Room inventory file not found: {ROOM_DATA_PATH}")
            return []

        with open(ROOM_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            data = data.get("rooms", [])

        return data

    def reload(self):
        self.rooms = self.load_rooms()

    def is_room_query(self, message: str) -> bool:
        q = normalize_text(message)

        if is_vague_room_message(message):
            return True

        room_words = [
            "kamar kosong",
            "kosong",
            "available",
            "ready",
            "tersedia",
            "masih ada",
            "ada kamar",
            "kamar ada",
            "room",
            "kamar mandi dalam",
            "kamar mandi luar",
            "1 juta",
            "1 5 juta",
            "harga kamar",
            "sewa kamar",
            "masuk kapan",
            "check in",
            "check-in"
        ]

        location_words = [
            "lippo",
            "meadow",
            "meadow green",
            "jababeka",
            "pavilion",
            "lembah",
            "lembah hijau",
            "katalia"
        ]

        return any(word in q for word in room_words) or any(word in q for word in location_words)

    def get_property_name(self, room):
        return (
            room.get("property_name")
            or room.get("property")
            or room.get("house")
            or room.get("location")
            or "lokasi belum tercatat"
        )

    def get_address_short(self, room):
        return str(room.get("address_short") or "").strip()

    def get_area(self, room):
        property_name = normalize_text(self.get_property_name(room))

        if "pavilion" in property_name:
            return "Jababeka"

        if "katalia" in property_name:
            return "Lembah Hijau"

        return "Meadow Green"

    def display_area_name(self, area: str) -> str:
        if area == "Meadow Green":
            return "Lippo/Meadow Green"

        if area == "Jababeka":
            return "Jababeka/Pavilion"

        if area == "Lembah Hijau":
            return "Lembah Hijau/Katalia"

        return area

    def get_bathroom_type(self, room):
        value = (
            room.get("bathroom_type")
            or room.get("room_type")
            or ""
        )
        return str(value or "").strip().lower()

    def get_price(self, room):
        return (
            room.get("price_monthly")
            or room.get("price")
            or room.get("monthly_price")
            or None
        )

    def get_status(self, room):
        return str(room.get("status") or "").strip().lower()

    def get_window_type(self, room):
        existing = str(room.get("window_type") or "").strip().lower()

        if existing:
            return existing

        bathroom_type = self.get_bathroom_type(room)
        price = self.get_price(room)

        try:
            price = int(float(price))
        except Exception:
            price = None

        if bathroom_type == "kamar mandi luar" and price and price > 1000000:
            return "jendela depan"

        return ""

    def available_rooms(self):
        return [
            room for room in self.rooms
            if self.get_status(room) == "available"
        ]

    def mentioned_property(self, message: str):
        q = normalize_text(message)

        property_names = sorted(
            set(self.get_property_name(room) for room in self.rooms),
            key=len,
            reverse=True
        )

        for property_name in property_names:
            if not property_name:
                continue

            p_norm = normalize_text(property_name)

            if p_norm and p_norm in q:
                return property_name

            tokens = p_norm.split()
            if tokens and all(token in q for token in tokens):
                return property_name

        return None

    def has_specific_room_filter(self, message: str) -> bool:
        areas = detect_areas(message)
        property_name = self.mentioned_property(message)
        bathroom_type = detect_bathroom_type(message)
        price_query = parse_price_query(message)

        return bool(areas or property_name or bathroom_type or price_query)

    def is_broad_availability_question(self, message: str) -> bool:
        q = normalize_text(message)

        broad_words = [
            "ada kamar kosong",
            "kamar kosong",
            "masih ada kamar",
            "ada kamar",
            "kosong",
            "ready",
            "available",
            "tersedia"
        ]

        asks_availability = any(word in q for word in broad_words)

        return asks_availability and not self.has_specific_room_filter(message)

    def filter_rooms(self, message: str):
        rooms = self.available_rooms()

        areas = detect_areas(message)
        property_name = self.mentioned_property(message)
        bathroom_type = detect_bathroom_type(message)
        price_query = parse_price_query(message)

        if areas:
            rooms = [
                room for room in rooms
                if self.get_area(room) in areas
            ]

        if property_name:
            rooms = [
                room for room in rooms
                if normalize_text(self.get_property_name(room)) == normalize_text(property_name)
            ]

        if bathroom_type:
            rooms = [
                room for room in rooms
                if bathroom_type in self.get_bathroom_type(room)
            ]

        if price_query:
            rooms = [
                room for room in rooms
                if self.get_price(room) and int(float(self.get_price(room))) == price_query
            ]

        filters = {
            "areas": areas,
            "property_name": property_name,
            "bathroom_type": bathroom_type,
            "price_query": price_query
        }

        return rooms, filters

    def summarize_by_house(self, rooms):
        grouped = {}

        for room in rooms:
            area = self.display_area_name(self.get_area(room))
            property_name = self.get_property_name(room)
            address_short = self.get_address_short(room)
            bathroom_type = self.get_bathroom_type(room) or "tipe kamar"
            price = self.get_price(room)
            window_type = self.get_window_type(room)

            house_key = (area, property_name, address_short)

            if house_key not in grouped:
                grouped[house_key] = []

            option = {
                "bathroom_type": bathroom_type,
                "price": price,
                "window_type": window_type
            }

            if option not in grouped[house_key]:
                grouped[house_key].append(option)

        return grouped

    def build_public_availability_reply(self, rooms, filters):
        grouped = self.summarize_by_house(rooms)

        if not grouped:
            return (
                "Untuk tipe kamar itu, saat ini belum ada yang tercatat tersedia. "
                "Aku cekkan dulu ke admin untuk update paling baru ya kak."
            )

        area_groups = {}

        for (area, property_name, address_short), options in grouped.items():
            if area not in area_groups:
                area_groups[area] = []

            options = sorted(
                options,
                key=lambda x: (
                    0 if "dalam" in x["bathroom_type"] else 1,
                    int(x["price"] or 0)
                )
            )

            option_texts = []

            for option in options:
                bathroom_type = option["bathroom_type"]
                price = option["price"]
                window_type = option["window_type"]

                text = f"{bathroom_type} {format_rupiah(price)}/bulan"

                if window_type:
                    text += f" ({window_type})"

                option_texts.append(text)

            house_label = property_name

            if address_short:
                house_label += f" - {address_short}"

            area_groups[area].append(
                f"{house_label}: {human_join(option_texts)}"
            )

        if len(area_groups) == 1:
            area_name = list(area_groups.keys())[0]
            house_lines = area_groups[area_name]

            if len(house_lines) == 1:
                reply = f"Ada kak, untuk area {area_name} tersedia di {house_lines[0]}."
            else:
                reply = f"Ada kak, untuk area {area_name} tersedia di:\n- " + "\n- ".join(house_lines) + "."

        else:
            area_lines = []

            for area_name, house_lines in area_groups.items():
                area_lines.append(
                    f"{area_name}: " + "; ".join(house_lines)
                )

            reply = "Ada kak, pilihannya:\n- " + "\n- ".join(area_lines) + "."

        if any(
            self.get_bathroom_type(room) == "kamar mandi luar"
            and self.get_price(room)
            and int(float(self.get_price(room))) > 1000000
            for room in rooms
        ):
            reply += " Perbedaan harga biasanya karena ada kamar mandi luar dengan jendela depan."

        reply += " Depositnya Rp500.000 ya kak. Rencana masuknya kapan?"

        return reply

    def answer_room_query(self, message: str, allow_followup_question: bool = True) -> dict:
        if not self.rooms:
            return {
                "handled": True,
                "reply": "Untuk info kamar, kakak mau tanya harga, fasilitas, atau ketersediaan kamar kosong?",
                "needs_admin": False,
                "matched_source": "room_inventory_missing",
                "followup_needed": False
            }

        if is_vague_room_message(message):
            return {
                "handled": True,
                "reply": (
                    "Kakak mau tanya tentang harga kamar, fasilitas kamar, "
                    "atau ketersediaan kamar kosong?"
                ),
                "needs_admin": False,
                "matched_source": "room_inventory",
                "followup_needed": False
            }

        if allow_followup_question and self.is_broad_availability_question(message):
            return {
                "handled": True,
                "reply": (
                    "Ada beberapa lokasi kost, kak. Kakak mau cek area yang mana: "
                    "Lippo/Meadow Green, Jababeka/Pavilion, atau Lembah Hijau/Katalia?"
                ),
                "needs_admin": False,
                "matched_source": "room_inventory",
                "followup_needed": True
            }

        rooms, filters = self.filter_rooms(message)

        if not rooms:
            areas = filters.get("areas", [])
            property_name = filters.get("property_name")

            if areas:
                area_text = " atau ".join([self.display_area_name(area) for area in areas])
                return {
                    "handled": True,
                    "reply": (
                        f"Untuk area {area_text}, saat ini belum ada kamar yang tercatat tersedia sesuai pertanyaan kakak. "
                        "Mau aku cekkan dulu ke admin untuk update terbaru?"
                    ),
                    "needs_admin": True,
                    "matched_source": "room_inventory",
                    "followup_needed": False
                }

            if property_name:
                return {
                    "handled": True,
                    "reply": (
                        f"Untuk {property_name}, saat ini belum ada kamar yang tercatat tersedia sesuai pertanyaan kakak. "
                        "Mau aku cekkan dulu ke admin?"
                    ),
                    "needs_admin": True,
                    "matched_source": "room_inventory",
                    "followup_needed": False
                }

            return {
                "handled": True,
                "reply": (
                    "Untuk tipe kamar itu, saat ini belum ada yang tercatat tersedia. "
                    "Aku cekkan dulu ke admin untuk update paling baru ya kak."
                ),
                "needs_admin": True,
                "matched_source": "room_inventory",
                "followup_needed": False
            }

        reply = self.build_public_availability_reply(rooms, filters)

        return {
            "handled": True,
            "reply": reply,
            "needs_admin": False,
            "matched_source": "room_inventory",
            "available_count": len(rooms),
            "followup_needed": False
        }
