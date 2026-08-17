from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from router import rt
from faq import chain, load_faq_data
from sql import generate_query, run_query
from pathlib import Path
from typing import Any, Annotated

class ChatRequest(BaseModel):
    query : str = Field(min_length = 1)

class ChatResponse(BaseModel):
    response : str | list[dict[str, Any]]
    route : str

class FakeRoute:
    name = "FAQ"

app = FastAPI()

def get_router():
    return rt

def fake_router(query):
    return FakeRoute()

faq_path = Path(__file__).parent / "app/resources/faq_data.csv"
load_faq_data(faq_path)

@app.post("/chat", response_model = ChatResponse)
def chat(message: ChatRequest, router: Annotated[Any, Depends(get_router)]):
    query = message.query
    route = router(query)

    if route.name == "FAQ":
        try:
            answer = chain(query)
            return {"response": answer, "route" : route.name}
        except ConnectionError:
                     raise HTTPException(
                                status_code = 503,
                                detail = "LLM temporarily unavailable for FAQ route"
                            )


    elif route.name == "SQL":
        try:
            sql_query = generate_query(query)
        except ConnectionError:
            raise HTTPException(
                    status_code = 503,
                    detail = "LLM temporarily unavailable for SQL route"
                )
        try:
            result = run_query(sql_query)
            return {"response": result.to_dict(orient="records"), "route": route.name}
        except ConnectionError:
             raise HTTPException(
                        status_code = 503,
                        detail = "Database service temporarily unavailable"
                    )

    else:
        # treat as general FAQ — let the LLM handle it
        try:
            answer = chain(query)
            return {"response": answer, "route": "General"}
        except ConnectionError:
            raise HTTPException(
                    status_code = 503,
                    detail = "LLM temporarily unavailable for General route"
                )