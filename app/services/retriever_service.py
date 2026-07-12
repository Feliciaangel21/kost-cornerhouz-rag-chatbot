import json
import os
import pickle
import re
from pathlib import Path


INDEX_PATH = Path("vector_store/faiss.index")
META_PATH = Path("vector_store/faq_metadata.pkl")
FAQ_JSON_PATH = Path("data/faq_kost.json")

MODEL_NAME = "LazarusNLP/all-indo-e5-small-v4"


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def expand_query_terms(text: str) -> str:
    q = normalize_text(text)
    expansions = []

    synonym_groups = [
        ["listrik", "token", "token listrik", "bayar listrik", "biaya listrik"],
        ["berdua", "dua orang", "2 orang", "diisi 2 orang", "sharing", "share kamar", "satu kamar berdua"],
        ["survey", "survei", "lihat kamar", "liat kamar", "cek kamar", "datang lihat"],
        ["booking", "book", "pesan", "keep", "dp", "ambil kamar"],
        ["pasangan", "pacar", "lawan jenis", "pasutri", "suami istri"],
    ]

    for group in synonym_groups:
        if any(normalize_text(term) in q for term in group):
            expansions.extend(group)

    if re.search(r"\b2\b", q) and any(term in q for term in ["orang", "org", "penghuni"]):
        expansions.extend(["dua orang", "berdua", "share kamar"])

    if expansions:
        return f"{q} {' '.join(expansions)}"

    return q


def detect_intent(query: str) -> str | None:
    q = expand_query_terms(query)

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
    q = expand_query_terms(query)

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
        self.model = None
        self.index = None
        self.vector_enabled = os.getenv("ENABLE_VECTOR_SEARCH", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        self.faqs = self._load_faqs()

    def _load_faqs(self):
        if FAQ_JSON_PATH.exists():
            with open(FAQ_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)

        with open(META_PATH, "rb") as f:
            return pickle.load(f)

    def _ensure_vector_index(self) -> bool:
        if not self.vector_enabled:
            return False

        if self.model is not None and self.index is not None:
            return True

        try:
            import faiss
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(MODEL_NAME)
            self.index = faiss.read_index(str(INDEX_PATH))
            return True
        except Exception as exc:
            print(f"[Retriever] Vector search unavailable, using lexical search: {exc}")
            self.vector_enabled = False
            self.model = None
            self.index = None
            return False

    def _lexical_search(self, query: str, top_k: int):
        query_norm = expand_query_terms(query)
        query_tokens = set(query_norm.split())
        results = []

        for faq in self.faqs:
            haystack = normalize_text(
                " ".join([
                    faq.get("category", ""),
                    faq.get("question", ""),
                    faq.get("answer", ""),
                    " ".join(faq.get("keywords", [])),
                ])
            )
            haystack_tokens = set(haystack.split())
            overlap = len(query_tokens.intersection(haystack_tokens))
            overlap_score = overlap / max(len(query_tokens), 1)
            k_bonus = keyword_bonus(query, faq)
            i_bonus = intent_bonus(query, faq)
            final_score = overlap_score + k_bonus + i_bonus

            results.append({
                "score": final_score,
                "semantic_score": 0.0,
                "keyword_bonus": k_bonus,
                "intent_bonus": i_bonus,
                "faq": faq
            })

        results = sorted(results, key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search(self, query: str, top_k: int = 5):
        if not self._ensure_vector_index():
            return self._lexical_search(query, top_k)

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
