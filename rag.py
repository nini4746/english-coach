"""Grammar-reference RAG for the English coach.

Indexes a small corpus of Korean-learner grammar/usage notes (docs/) so the
agent can retrieve the relevant rule and cite it when explaining an error.
Same pipeline as the Context-Management project: chunk -> embed -> store -> search.
Embeddings are local (sentence-transformers); no API key needed.
"""
import os
import pickle

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
INDEX_PATH = os.path.join(os.path.dirname(__file__), "grammar_index.pkl")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_model = None


def chunk_text(text: str, target_chars: int = 900, overlap_chars: int = 100) -> list[str]:
    """Sliding-window chunks, preferring paragraph (\\n\\n) boundaries."""
    text = text.strip()
    if not text:
        return []
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + target_chars, n)
        if end < n:
            para = text.rfind("\n\n", start + target_chars * 2 // 3, end)
            if para != -1:
                end = para
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _embed(texts: list[str]) -> list[list[float]]:
    return _get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def build_index() -> int:
    """Walk docs/, chunk + embed each .md/.txt, persist to grammar_index.pkl."""
    records, cid = [], 0
    for name in sorted(os.listdir(DOCS_DIR)):
        if not name.lower().endswith((".md", ".txt")):
            continue
        with open(os.path.join(DOCS_DIR, name), encoding="utf-8") as f:
            chunks = chunk_text(f.read())
        if not chunks:
            continue
        for i, (ch, vec) in enumerate(zip(chunks, _embed(chunks))):
            records.append({"id": cid, "source": name, "chunk_index": i, "text": ch, "embedding": vec})
            cid += 1
    with open(INDEX_PATH, "wb") as f:
        pickle.dump(records, f)
    return len(records)


def _load():
    if not os.path.exists(INDEX_PATH):
        build_index()
    with open(INDEX_PATH, "rb") as f:
        return pickle.load(f)


def search(query: str, k: int = 3) -> list[dict]:
    """Return top-k reference chunks for a query (cosine over unit vectors)."""
    records = _load()
    if not records:
        return []
    [qv] = _embed([query])
    scored = sorted(records, key=lambda r: 1.0 - sum(a * b for a, b in zip(r["embedding"], qv)))
    return scored[:k]


if __name__ == "__main__":
    print(f"Indexed {build_index()} chunks -> {os.path.basename(INDEX_PATH)}")
