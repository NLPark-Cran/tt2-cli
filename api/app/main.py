"""FastAPI 应用装配（薄）。"""

from fastapi import FastAPI

from .core.errors import register_error_handlers
from .core.logging import setup_logging
from .routers import auth, domains, sites, tasks, tokens

setup_logging()

app = FastAPI(title="tt2-api", version="0.1.0", docs_url=None, redoc_url=None)
register_error_handlers(app)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(tokens.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(sites.router, prefix="/api/v1")
app.include_router(domains.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict:
    return {"ok": True, "service": "tt2-api", "version": "0.1.0"}
