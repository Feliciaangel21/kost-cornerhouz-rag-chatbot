import csv
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv()

ROOMS_URL = os.getenv("ROOMS_SHEET_CSV_URL")

CSV_PATH = Path("data/rooms_public.csv")
JSON_PATH = Path("data/room_inventory_public_clean.json")


def clean(value):
    return str(value or "").strip()


def to_int_or_none(value):
    value = clean(value)

    if not value:
        return None

    value = value.replace(".", "").replace(",", "")

    try:
        return int(value)
    except ValueError:
        return None


def normalize_status(value):
    status = clean(value).lower()

    allowed = ["available", "occupied", "reserved", "maintenance"]

    if status in allowed:
        return status

    if status in ["kosong", "ready", "tersedia"]:
        return "available"

    if status in ["isi", "terisi", "penuh"]:
        return "occupied"

    return "occupied"


def download_csv():
    if not ROOMS_URL or "PASTE_" in ROOMS_URL:
        raise ValueError("ROOMS_SHEET_CSV_URL is missing or invalid in .env")

    response = requests.get(ROOMS_URL, timeout=30)
    response.raise_for_status()

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    CSV_PATH.write_text(response.text, encoding="utf-8")

    print(f"Downloaded rooms CSV to {CSV_PATH}")


def convert_csv_to_json():
    rooms = []

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        required_columns = [
            "property_name",
            "room_number",
            "bathroom_type",
            "price_monthly",
            "deposit",
            "status",
            "available_from",
            "public_note",
            "last_updated"
        ]

        for column in required_columns:
            if column not in reader.fieldnames:
                raise ValueError(
                    f"Missing rooms column: {column}. Found columns: {reader.fieldnames}"
                )

        for row in reader:
            property_name = clean(row.get("property_name"))
            room_number = clean(row.get("room_number"))

            if not property_name and not room_number:
                continue

            bathroom_type = clean(row.get("bathroom_type")).lower()
            price_monthly = to_int_or_none(row.get("price_monthly"))
            deposit = to_int_or_none(row.get("deposit")) or 500000
            status = normalize_status(row.get("status"))

            room = {
                "property_name": property_name,
                "room_number": room_number,
                "bathroom_type": bathroom_type,
                "price_monthly": price_monthly,
                "deposit": deposit,
                "status": status,
                "available_from": clean(row.get("available_from")) or None,
                "public_note": clean(row.get("public_note")),
                "last_updated": clean(row.get("last_updated")),

                "has_ac": True,
                "has_wifi": True,
                "has_shared_kitchen": True,
                "has_shared_fridge": True,
                "electricity": "token bayar sendiri",
                "fingerprint_access": True,
                "capacity": 1,
                "accepts_pasutri": False,
                "has_water_heater": bathroom_type == "kamar mandi dalam"
            }

            rooms.append(room)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(rooms, f, ensure_ascii=False, indent=2)

    available_count = len([room for room in rooms if room["status"] == "available"])

    print(f"Converted {len(rooms)} room rows to {JSON_PATH}")
    print(f"Available rooms: {available_count}")


def main():
    download_csv()
    convert_csv_to_json()
    print("Rooms sync complete.")


if __name__ == "__main__":
    main()
