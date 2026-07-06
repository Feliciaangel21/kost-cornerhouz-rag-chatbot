import pickle
import re
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer


INDEX_PATH = Path("vector_store/faiss.index")
META_PATH = Path("vector_store/faq_metadata.pkl")

MODEL_NAME = "LazarusNLP/all-indo-e5-small-v4"


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_intent(query: str) -> str | None:
    q = normalize_text(query)

    price_words = [
        "harga", "berapa", "biaya", "tarif", "sewa",
        "1 juta", "1500000", "bayar"
    ]

    availability_words = [
        "kosong", "tersedia", "available", "ready",
        "masih ada", "ada kamar", "slot"
    ]

    facility_words = [
        "fasilitas", "wifi", "internet", "ac", "water heater",
        "dapur", "kulkas", "fingerprint"
    ]

    rule_words = [
        "boleh", "larangan", "dilarang", "aturan", "tamu",
        "pacar", "nginep", "menginap", "rokok", "hewan"
    ]

    payment_words = [
        "deposit", "jaminan", "denda", "telat", "terlambat",
        "pembayaran", "transfer"
    ]

    checkout_words = [
        "checkout", "check out", "keluar", "extend", "perpanjang"
    ]

    if any(word in q for word in availability_words):
        return "ketersediaan"

    if any(word in q for word in payment_words):
        return "pembayaran"

    if any(word in q for word in checkout_words):
        return "checkout"

    # Important: if query has AC + berapa/harga, treat as price
    if "ac" in q and any(word in q for word in ["berapa", "harga", "biaya", "sewa"]):
        return "harga"

    if any(word in q for word in price_words):
        return "harga"

    if any(word in q for word in rule_words):
        return "aturan"

    if any(word in q for word in facility_words):
        return "fasilitas"

    return None


def keyword_bonus(query: str, faq: dict) -> float:
    q = normalize_text(query)

    bonus = 0.0

    # FAQ keyword match
    for keyword in faq.get("keywords", []):
        keyword_norm = normalize_text(keyword)
        if keyword_norm and keyword_norm in q:
            bonus += 0.05

    # FAQ question phrase overlap
    question = normalize_text(faq.get("question", ""))
    question_tokens = set(question.split())
    query_tokens = set(q.split())

    if question_tokens:
        overlap = len(question_tokens.intersection(query_tokens)) / len(question_tokens)
        bonus += overlap * 0.08

    return min(bonus, 0.20)


def intent_bonus(query: str, faq: dict) -> float:
    intent = detect_intent(query)
    category = faq.get("category", "")

    if not intent:
        return 0.0

    # Direct category match
    if intent == category:
        return 0.15

    # Grouped category matches
    if intent == "aturan" and category in ["aturan", "aturan_tamu", "kapasitas"]:
        return 0.15

    if intent == "pembayaran" and category in ["pembayaran", "deposit"]:
        return 0.15

    if intent == "harga" and category in ["harga", "tipe_kamar"]:
        return 0.15

    if intent == "fasilitas" and category in ["fasilitas", "dapur", "laundry", "listrik", "keamanan", "air"]:
        return 0.12

    return 0.0


class RetrieverService:
    def __init__(self):
        self.model = SentenceTransformer(MODEL_NAME)
        self.index = faiss.read_index(str(INDEX_PATH))

        with open(META_PATH, "rb") as f:
            self.faqs = pickle.load(f)

    def search(self, query: str, top_k: int = 5):
        query_text = f"query: {query}"

        query_embedding = self.model.encode(
            [query_text],
            convert_to_numpy=True,
            normalize_embeddings=True
        ).astype("float32")

        # Retrieve more candidates first, then rerank
        candidate_k = min(max(top_k * 4, 20), len(self.faqs))
        scores, indices = self.index.search(query_embedding, candidate_k)

        results = []

        for semantic_score, idx in zip(scores[0], indices[0]):
            faq = self.faqs[idx]

            k_bonus = keyword_bonus(query, faq)
            i_bonus = intent_bonus(query, faq)

            final_score = float(semantic_score) + k_bonus + i_bonus

            results.append({
                "score": final_score,
                "semantic_score": float(semantic_score),
                "keyword_bonus": k_bonus,
                "intent_bonus": i_bonus,
                "faq": faq
            })

        results = sorted(results, key=lambda x: x["score"], reverse=True)

        return results[:top_k]
