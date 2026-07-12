from dotenv import load_dotenv

load_dotenv()

from app.services.nlu_service import NLUService

nlu_service = NLUService()

test_messages = [
    "mau tnaya",
    "kamar kosonh?",
    "kost daerah lippo",
    "lippo msh ada ga kak",
    "boleh liat foto?",
    "ada pict kamar?",
    "mau booking kamar",
    "mau survey besok",
    "untuk bulan depan",
    "buan depan",
    "tgl 7 bulan juli",
    "tanggal 7 juli",
    "katalia",
    "ada kamar kosong di lembah?",
    "katalia buat cowok bisa?",
    "pinus hijau 3 no 7 khusus cewe?",
    "bedanya apa kak?",
]

print("LLM enabled:", nlu_service.enabled)
print("Model:", nlu_service.model)
print("Base URL:", nlu_service.base_url)

for message in test_messages:
    result = nlu_service.analyze(message)

    print("\nUSER:", message)
    print("intent:", result.intent)
    print("route:", result.route)
    print("clean_query:", result.clean_query)
    print("area:", result.area)
    print("move_in_date:", result.move_in_date)
    print("wants_booking:", result.wants_booking)
    print("wants_survey:", result.wants_survey)
    print("needs_admin:", result.needs_admin)
    print("confidence:", result.confidence)
    print("reason:", result.reason)

