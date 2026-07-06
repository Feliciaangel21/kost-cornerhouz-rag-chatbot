# Kost.cornerhouz RAG Chatbot

An Indonesian FAQ and room availability chatbot for a kost business.  
This project was built to automate repeated tenant questions about room prices, facilities, rules, deposits, and available rooms.

## Features

- RAG chatbot for kost FAQ
- Room availability search
- Google Sheets data sync
- Admin-protected endpoints
- Web chat interface

## Tech Stack

- Python
- FastAPI
- FAISS
- Sentence Transformers
- HTML
- CSS
- JavaScript
- Google Sheets CSV Sync

## Project Overview

The chatbot uses a retrieval-based system to match user questions with relevant FAQ data.

For room availability, it reads public-safe room inventory data and responds with room type, area, price, deposit, and availability information without exposing private tenant details.

The system is designed to avoid hallucinating unavailable information. If the chatbot cannot confidently answer a question, it asks for clarification or escalates the question to admin.

## Main Use Cases

- Answer FAQ about kost rules and facilities
- Check available rooms by area
- Explain room price differences
- Sync FAQ and room data from Google Sheets
- Escalate unclear questions to admin

## Example Questions

- Ada kamar kosong?
- Lippo ada kamar?
- Harga kamar mandi dalam berapa?
- Bedanya kamar 1 juta dan 1.3 juta apa?
- Deposit berapa?
- Lawan jenis boleh masuk kamar?
- Ada WiFi?
- Listrik sudah termasuk?

## How to Run Locally

1. Create and activate virtual environment

    python -m venv .venv
    source .venv/bin/activate

2. Install dependencies

    pip install -r requirements.txt

3. Run the app

    python -m uvicorn app.main:app --reload

4. Open in browser

    http://127.0.0.1:8000

## Environment Variables

Create a `.env` file in the project root:

    FAQ_SHEET_CSV_URL=your_faq_google_sheet_csv_url
    ROOMS_SHEET_CSV_URL=your_rooms_google_sheet_csv_url
    ADMIN_TOKEN=your_admin_token

## Admin Endpoints

Admin endpoints are protected using an admin token.

Examples:

- /admin/sync-faq
- /admin/sync-rooms
- /admin/sync-all
- /admin/logs
- /admin/reload-rooms

## Notes

This project is built as an MVP for a real kost business use case.  
The goal is to reduce repetitive admin work by answering common tenant questions automatically.

