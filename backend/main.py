from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import settings
from models import User
from routers import courses, grading, images, questions, student, submissions
from schemas import UserOut
from security import get_current_user

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Web-End API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Vendored KaTeX (backend/static/katex). doc_renderer's Playwright pass
# loads equation CSS/JS from this mount rather than a CDN, so rendering
# stays fully offline and reproducible — and unauthenticated, since the
# headless browser fetching it has no session.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

api = APIRouter(prefix="/api")


@api.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


api.include_router(courses.router)
api.include_router(questions.router)
api.include_router(submissions.router)
api.include_router(images.router)
api.include_router(grading.router)
api.include_router(student.router)
app.include_router(api)


@app.get("/health")
def health():
    return {"status": "ok"}
