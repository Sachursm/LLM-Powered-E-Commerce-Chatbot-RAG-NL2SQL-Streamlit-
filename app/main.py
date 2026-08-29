from fastapi import FastAPI

from app.routers.products import router as products_router
from app.routers.categories import router as categories_router
from app.routers.auth import router as auth_router
from app.routers.test_auth import router as test_auth_router
from app.routers.users import router as user_router
from app.routers.admin import router as admin_router
from app.routers.seller import router as seller_router
from app.routers.cart import router as cart_router

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
app.include_router(categories_router)
app.include_router(auth_router)
app.include_router(test_auth_router)
app.include_router(user_router)
app.include_router(admin_router)
app.include_router(seller_router)
app.include_router(cart_router)


