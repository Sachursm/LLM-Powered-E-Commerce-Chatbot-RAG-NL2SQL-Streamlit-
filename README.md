# 🛒 E‑Commerce Chatbot (LLM + RAG + SQL)

An intelligent e‑commerce assistant that answers user questions using:

* FAQ semantic search (ChromaDB + embeddings)
* Natural‑language‑to‑SQL queries (SQLite)
* General conversation via LLM

The chatbot is deployed with a Streamlit interface and runs in a WSL Ubuntu environment.

---

# 🚀 Features

## 1️⃣ FAQ Retrieval (RAG)

* FAQ questions stored in CSV
* Embedded using SentenceTransformers (`all‑MiniLM‑L6‑v2`)
* Stored in ChromaDB vector database
* User query → semantic search → best FAQ match
* Retrieved Q&A passed to LLM to generate final response

## 2️⃣ Natural Language → SQL

* User asks product/database questions
* LLM converts natural language → SQL query
* Query executed on SQLite database
* Results formatted as table response

## 3️⃣ Intent Routing

Router detects user intent:

* FAQ question → vector search
* Database question → SQL pipeline
* General chat (hi, who are you, etc.) → LLM response

## 4️⃣ Streamlit Chat UI

* Interactive chat interface
* Shows table outputs for SQL queries
* Displays conversational responses

---

# 🧠 Models & AI Stack

**LLM:** `llama‑3.3‑70b‑versatile` (Groq API)

**Embeddings:**
`SentenceTransformerEmbeddingFunction`
`model = all‑MiniLM‑L6‑v2`

**Vector DB:** ChromaDB

**Database:** SQLite

**Data Processing:** Pandas

**Frontend:** Streamlit

**Environment:** WSL (Ubuntu 22.04)

---

# 📂 Project Structure

```
E_COMMERCE_CHATBOT/
│
├── app/resources/
│   ├── faq_data.csv      # FAQ questions & answers
│   └── db.sqlite         # Product database
│
├── faq.py                # FAQ semantic search pipeline
├── sql.py                # NL → SQL → SQLite execution
├── router.py             # Intent classification logic
├── chat.py               # Streamlit interface
│
├── venv/
├── web_venv/
├── .env
└── .gitignore
```

---

# ⚙️ How It Works

## FAQ Flow

1. Load FAQ CSV
2. Embed questions
3. Store in ChromaDB
4. User query → similarity search
5. Retrieved answer → sent to LLM
6. LLM generates natural reply

## SQL Flow

1. User question
2. LLM generates SQL query
3. Query executed on SQLite
4. Results returned as table

## Router Flow

```
User Query
   ↓
Intent Detection
   ↓
FAQ | SQL | General LLM
```
---

## Demo

### Chat UI
> The main Streamlit chat interface

![Chat UI](https://github.com/Sachursm/LLM-Powered-E-Commerce-Chatbot-RAG-NL2SQL-Streamlit-/blob/2b8a41b2a4214937b0fbb0873051a2f72367399a/images/fontui.png)

---

### General Conversation
> Open-ended questions answered by Groq Llama-3

![Normal Chat UI](https://github.com/Sachursm/LLM-Powered-E-Commerce-Chatbot-RAG-NL2SQL-Streamlit-/blob/2b8a41b2a4214937b0fbb0873051a2f72367399a/images/normalui.png)

---

### FAQ Semantic Search
> User asks a product question — ChromaDB finds the closest match from the knowledge base

![FAQ UI](https://github.com/Sachursm/LLM-Powered-E-Commerce-Chatbot-RAG-NL2SQL-Streamlit-/blob/2b8a41b2a4214937b0fbb0873051a2f72367399a/images/faqui.png)

---

### Natural Language to SQL
> User types a plain English question — the system converts it to a SQL query and runs it

![SQL UI](https://github.com/Sachursm/LLM-Powered-E-Commerce-Chatbot-RAG-NL2SQL-Streamlit-/blob/2b8a41b2a4214937b0fbb0873051a2f72367399a/images/sqlui.png)

---

### SQL Table Result
> Structured database results displayed as a clean table

![Table UI](https://github.com/Sachursm/LLM-Powered-E-Commerce-Chatbot-RAG-NL2SQL-Streamlit-/blob/2b8a41b2a4214937b0fbb0873051a2f72367399a/images/tableui.png)

---

# 🖥️ Installation

## 1️⃣ Clone

```
git clone <repo_url>
cd E_COMMERCE_CHATBOT
```

## 2️⃣ WSL Setup

Project was developed in:

* WSL Ubuntu 22.04
* Python 3.10+

## 3️⃣ Create Environment

```
python -m venv venv
source venv/bin/activate
```

## 4️⃣ Install Dependencies

```
pip install streamlit chromadb pandas sentence-transformers sqlite-utils groq python-dotenv
```

## 5️⃣ Add API Key

Create `.env`

```
GROQ_API_KEY=your_key_here
```

---

# ▶️ Run Chatbot

```
streamlit run chat.py
```

Open browser:

```
http://localhost:8501
```

---

# 📊 Data Sources

## FAQ

`faq_data.csv`

* question
* answer

## SQL Database

`db.sqlite`
Contains structured product data used for SQL queries.

⚠️ Note: Web‑scraped data was planned but not completed. Database answers depend only on SQLite content, so some questions may not be answerable.

---

# 💬 Example Queries

### FAQ

* What is the return policy?
* Do you offer cash on delivery?

### SQL

* Show shoes under 3000
* List Puma products

### General

* Hi
* Who are you?

---

# ⚠️ Limitations

* Limited SQL database coverage
* No live product scraping
* Router may misclassify ambiguous queries
* Depends on LLM for SQL accuracy

---

# 🧩 Future Improvements

* Add web scraping pipeline
* Expand product database
* Add hybrid search (FAQ + SQL)
* Improve intent classifier
* Add conversation memory

---

# 👨‍💻 Author

Sachu Retna S M

AI / LLM / RAG based E‑Commerce Chatbot using Groq + ChromaDB + SQLite.
