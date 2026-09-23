"""
FastAPI application entrypoint. Run with:

    uvicorn app.main:app --reload

This is the "headless" API layer: it has no server-rendered views of its
own - every screen described in PARTs 4-6 of the spec is built by the
existing frontend calling these JSON endpoints.
"""
import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import admin, appointments, auth, businesses, resources, users

logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)

app = FastAPI(
    title=settings.APP_NAME,
    description="Headless REST API for the multi-industry appointment system.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(businesses.router, prefix=settings.API_V1_PREFIX)
app.include_router(resources.router, prefix=settings.API_V1_PREFIX)
app.include_router(appointments.router, prefix=settings.API_V1_PREFIX)
app.include_router(admin.router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Uniform {"detail": ...} error shape (FastAPI's default) - kept explicit
    here as the one place to extend with problem+json etc. later if needed."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["meta"])
def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.get("/", tags=["meta"])
def root():
    return {
        "name": settings.APP_NAME,
        "docs": "/docs",
        "api_prefix": settings.API_V1_PREFIX,
    }
