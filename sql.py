from pathlib import Path
import sqlite3
import pandas as pd
from groq import Groq
from dotenv import load_dotenv
import re

load_dotenv()

groq_client = Groq()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "app/resources/db.sqlite"

SYSTEM_PROMPT = """
You are an expert assistant that converts natural language questions into valid SQLite SQL queries.

The database contains exactly one table named "product" with the following schema:

<schema>
product_link TEXT
title TEXT
brand TEXT
price INTEGER
discount REAL
avg_rating REAL
total_ratings INTEGER
</schema>

Rules you MUST follow:

- Only use table: product
- Only use listed columns
- Brand filter → brand LIKE '%name%'
- "under X" → price < X
- "above X" → price > X
- "between A and B" → price BETWEEN A AND B
- "X% discount" → discount >= X/100
- "above X rating" → avg_rating >= X
- cheapest → ORDER BY price ASC
- most expensive → ORDER BY price DESC
- highest rated → ORDER BY avg_rating DESC
- most popular → ORDER BY total_ratings DESC
- top/best/few → LIMIT 10
- number N → LIMIT N

Output ONLY SQL inside tags:

<sql>
SELECT ...
</sql>
"""

def generate_query(question: str):
    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        temperature=0.1,   # deterministic SQL
        max_completion_tokens=200,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question}
        ],
    )

    return completion.choices[0].message.content


def extract_sql(text: str) -> str:
    match = re.search(r"<sql>(.*?)</sql>", text, re.S | re.I)
    if match:
        return match.group(1).strip()
    return text.strip()

def run_query(query_text):
    sql = extract_sql(query_text)

    if sql.strip().upper().startswith("SELECT"):
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(sql, conn)
    else:
        raise ValueError("Only SELECT queries are allowed")

if __name__ == "__main__":
    
    # query = generate_query("What are the top 5 Nike products ")
    # print(query)
    # print(run_query(query))
    pass