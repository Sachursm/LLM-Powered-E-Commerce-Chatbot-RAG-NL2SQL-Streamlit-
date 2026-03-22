from fastapi import FastAPI
from router import rt
from faq import chain, load_faq_data
from sql import generate_query, run_query
from pathlib import Path

app = FastAPI()

faq_path = Path(__file__).parent / "app/resources/faq_data.csv"
load_faq_data(faq_path)

@app.post("/chat")
def chat(message: dict):
    query = message["query"]
    route = rt(query)

    if route.name == "FAQ":
        answer = chain(query)
        return {"response": answer}

    elif route.name == "SQL":
        sql_query = generate_query(query)
        result = run_query(sql_query)
        return {"response": result.to_dict(orient="records")}

    else:
        # treat as general FAQ — let the LLM handle it
        answer = chain(query)
        return {"response": answer}