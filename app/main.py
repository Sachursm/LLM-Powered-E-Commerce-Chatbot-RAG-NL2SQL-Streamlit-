from fastapi import FastAPI

from app.routers.products import router as products_router


app = FastAPI(
    title="E-Commerce API",
    version="1.0.0"
)

@app.get("/")
def root():
    return {
        "message": "E-Commerce API is running"
    }

app.include_router(products_router)


