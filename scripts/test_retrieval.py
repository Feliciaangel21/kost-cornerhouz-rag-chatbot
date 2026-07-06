import pickle
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer


INDEX_PATH = Path("vector_store/faiss.index")
META_PATH = Path("vector_store/faq_metadata.pkl")

MODEL_NAME = "LazarusNLP/all-indo-e5-small-v4"


def search(query: str, top_k: int = 3):
    model = SentenceTransformer(MODEL_NAME)
    index = faiss.read_index(str(INDEX_PATH))

    with open(META_PATH, "rb") as f:
        faqs = pickle.load(f)

    query_text = f"query: {query}"

    query_embedding = model.encode(
        [query_text],
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype("float32")

    scores, indices = index.search(query_embedding, top_k)

    results = []

    for score, idx in zip(scores[0], indices[0]):
        faq = faqs[idx]
        results.append({
            "score": float(score),
            "faq": faq
        })

    return results


if __name__ == "__main__":
    query = input("Tanya: ")
    results = search(query)

    print("\nTop results:")
    for result in results:
        print("-" * 50)
        print("Score:", result["score"])
        print("ID:", result["faq"]["id"])
        print("Category:", result["faq"]["category"])
        print("Question:", result["faq"]["question"])
        print("Answer:", result["faq"]["answer"])