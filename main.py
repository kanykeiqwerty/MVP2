from fastapi import FastAPI

from app.api.router import router

app = FastAPI(
    title="MVP2",
    description="API для MVP2",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.include_router(router)
