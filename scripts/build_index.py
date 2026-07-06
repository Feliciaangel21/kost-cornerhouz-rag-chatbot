import json
import pickle
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


FAQ_PATH = Path("data/faq_kost.json")
INDEX_PATH = Path("vector_store/faiss.index")
META_PATH = Path("vector_store/faq_metadata.pkl")

MODEL_NAME = "LazarusNLP/all-indo-e5-small-v4"


def make_search_text(faq: dict) -> str:
    keywords = ", ".join(faq.get("keywords", []))
    return (
        f"passage: "
        f"Kategori: {faq.get('category', '')}. "
        f"Pertanyaan: {faq.get('question', '')}. "
        f"Jawaban: {faq.get('answer', '')}. "
        f"Keyword: {keywords}."
    )


def main():
    with open(FAQ_PATH, "r", encoding="utf-8") as f:
        faqs = json.load(f)

    model = SentenceTransformer(MODEL_NAME)

    texts = [make_search_text(faq) for faq in faqs]
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True
    )

    embeddings = embeddings.astype("float32")
    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    faiss.write_index(index, str(INDEX_PATH))

    with open(META_PATH, "wb") as f:
        pickle.dump(faqs, f)

    print(f"Saved index to {INDEX_PATH}")
    print(f"Saved metadata to {META_PATH}")
    print(f"Total FAQ indexed: {len(faqs)}")


if __name__ == "__main__":
    main()