from fastapi import FastAPI
from pydantic import BaseModel, Field
from router import rt
from faq import chain, load_faq_data
from sql import generate_query, run_query
from pathlib import Path
from typing import Any

class ChatRequest(BaseModel):
    query : str = Field(min_length = 1)

class ChatResponse(BaseModel):
    response : str | list[dict[str, Any]]
    route : str

app = FastAPI()

faq_path = Path(__file__).parent / "app/resources/faq_data.csv"
load_faq_data(faq_path)

@app.post("/chat", response_model = ChatResponse)
def chat(message: ChatRequest):
    query = message.query
    route = rt(query)

    if route.name == "FAQ":
        answer = chain(query)
        return {"response": answer, "route" : route.name}

    elif route.name == "SQL":
        sql_query = generate_query(query)
        result = run_query(sql_query)
        return {"response": result.to_dict(orient="records"), "route": route.name}

    else:
        # treat as general FAQ — let the LLM handle it
        answer = chain(query)
        return {"response": answer, "route": "General"}