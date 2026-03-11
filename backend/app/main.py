from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.init_db import init_db
from app.api.routes import auth, cases, sources, chat, artifacts, exports, alerts


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.on_event("startup")
def on_startup():
    if settings.env == "dev":
        init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(cases.router, prefix="/cases", tags=["cases"])
app.include_router(sources.router, prefix="/sources", tags=["sources"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(artifacts.router, prefix="/studio", tags=["studio"])
app.include_router(exports.router, prefix="/exports", tags=["exports"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
