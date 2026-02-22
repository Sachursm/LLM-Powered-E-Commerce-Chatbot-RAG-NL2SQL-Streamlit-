import pandas as pd
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ---------- Paths ----------
faq_path = Path(__file__).parent / "app/resources/faq_data.csv"

# ---------- Clients ----------
chroma_client = chromadb.Client()
collection_name = "faq"

# Use same embedding model for add + query
embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

groq_client = Groq()


# ---------- Load CSV → Chroma ----------
def load_faq_data(path: Path):
    existing = [c.name for c in chroma_client.list_collections()]
    
    if collection_name in existing:
        print(f"Collection '{collection_name}' already exists. Skipping.")
        return

    df = pd.read_csv(path)

    docs = df["question"].astype(str).tolist()
    answers = df["answer"].astype(str).tolist()

    ids = [f"faq_{i}" for i in range(len(docs))]
    metadatas = [{"answer": ans} for ans in answers]

    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_func
    )

    collection.add(
        documents=docs,   # questions embedded
        metadatas=metadatas,
        ids=ids
    )

    print(f"Loaded {len(docs)} FAQ entries into Chroma.")


# ---------- Retrieve ----------
def get_faq_answer(query: str, k: int = 2):
    collection = chroma_client.get_collection(
        name=collection_name,
        embedding_function=embedding_func
    )

    results = collection.query(
        query_texts=[query],
        n_results=k
    )

    return results


# ---------- RAG Chain ----------
def chain(query: str):
    results = get_faq_answer(query)

    # extract answers from metadata
    answers = [m["answer"] for m in results["metadatas"][0]]
    context = "\n".join(answers)

    return generate_answer(query, context)


# ---------- LLM ----------
def generate_answer(query: str, context: str):
    prompt = f"""
        You are a helpful customer support assistant. Answer the question using ONLY the provided context.
        You can combine information from multiple context entries if needed. Be concise and accurate.
        If the answer is not in the context, say "I don't know", only bye pass this when the person is 
        asking about a specific product or service that is not in the context like in the example given below.

        --- Example ---
        Question: Do you ship internationally to Canada?
        Context: Yes, we offer international shipping to select countries.
        Answer: Yes, we offer international shipping to Canada, as it is one of our select countries.

        --- Now Answer ---
        Question: {query}
        Context: {context}
        Answer:
        """

    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_completion_tokens=512,
    )

    return completion.choices[0].message.content


# ---------- Run ----------
if __name__ == "__main__":
    load_faq_data(faq_path)

    query = "Can you do international shipping to USA?"
    
    print("\n--- Raw Retrieval ---")
    print(get_faq_answer(query))

    print("\n--- Final Answer ---")
    print(chain(query))
