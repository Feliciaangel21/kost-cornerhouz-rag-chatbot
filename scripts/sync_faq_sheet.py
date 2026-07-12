import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv()

FAQ_URL = os.getenv("FAQ_SHEET_CSV_URL")

CSV_PATH = Path("data/faq_kost.csv")
JSON_PATH = Path("data/faq_kost.json")


def to_bool(value: str) -> bool:
    return str(value).strip().lower() in ["true", "1", "yes", "y"]


def parse_keywords(value: str) -> list[str]:
    if not value:
        return []

    return [
        keyword.strip()
        for keyword in str(value).split(",")
        if keyword.strip()
    ]


def download_csv():
    if not FAQ_URL or "PASTE_" in FAQ_URL:
        raise ValueError("FAQ_SHEET_CSV_URL is missing or invalid in .env")

    response = requests.get(FAQ_URL, timeout=30)
    response.raise_for_status()

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    CSV_PATH.write_text(response.text, encoding="utf-8")

    print(f"Downloaded FAQ CSV to {CSV_PATH}")


def convert_csv_to_json():
    faqs = []

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        required_columns = [
            "id",
            "category",
            "question",
            "answer",
            "keywords",
            "is_dynamic",
            "needs_admin_confirmation"
        ]

        for column in required_columns:
            if column not in reader.fieldnames:
                raise ValueError(
                    f"Missing FAQ column: {column}. Found columns: {reader.fieldnames}"
                )

        for row in reader:
            if not str(row.get("id", "")).strip():
                continue

            faq = {
                "id": row["id"].strip(),
                "category": row["category"].strip(),
                "question": row["question"].strip(),
                "answer": row["answer"].strip(),
                "keywords": parse_keywords(row.get("keywords", "")),
                "is_dynamic": to_bool(row.get("is_dynamic", "false")),
                "needs_admin_confirmation": to_bool(row.get("needs_admin_confirmation", "false"))
            }

            faqs.append(faq)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(faqs, f, ensure_ascii=False, indent=2)

    print(f"Converted {len(faqs)} FAQ rows to {JSON_PATH}")


def rebuild_index():
    subprocess.run(
        [sys.executable, "scripts/build_index.py"],
        check=True
    )


def main():
    download_csv()
    convert_csv_to_json()
    should_rebuild_index = os.getenv("REBUILD_FAQ_INDEX", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if should_rebuild_index:
        rebuild_index()
    else:
        print("Skipped FAQ vector index rebuild.")
    print("FAQ sync complete.")


if __name__ == "__main__":
    main()
