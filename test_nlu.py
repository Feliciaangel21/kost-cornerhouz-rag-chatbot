from dotenv import load_dotenv

load_dotenv()

from app.services.nlu_service import NLUService

nlu = NLUService()

tests = [
    "kak lippo msh ada g?",
    "ada foto kamar?",
    "mau survey besok kak",
    "katalia buat cowo bisa?",
    "bedanya yg 1.5 sama 1.8 apa kak",
    "mau booking bulan depan tanggal 30",
]

for message in tests:
    result = nlu.analyze(message)
    print("\nUSER:", message)
    print(result.model_dump())