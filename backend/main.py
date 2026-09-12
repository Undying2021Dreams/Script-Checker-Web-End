from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import settings
from ratelimit import limiter
from models import User
from routers import courses, grading, images, questions, student, submissions
from schemas import UserOut
from security import get_current_user

app = FastAPI(title="Web-End API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        # Depends on a deployment setting as well as the account, so the
        # client is told rather than left to infer it from the role.
        can_create_courses=(
            settings.OPEN_COURSE_CREATION or user.role in ("teacher", "admin")
        ),
    )


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


# The built frontend, when there is one. Serving it from the same app
# means a single container to deploy and no cross-origin requests at all
# — the API is same-origin with the page that calls it. In development
# this directory doesn't exist and Vite serves the frontend instead.
_FRONTEND_DIST = Path(__file__).parent / "frontend_dist"

if _FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """
        Hand any unmatched path to the single-page app.

        Client-side routes like /courses/<id> are real URLs a user can
        reload or link to, but they exist only in the browser — the
        server has no such file, so without this a refresh would 404.
        Registered last so it can't shadow the API or /health, and it
        still returns a real 404 for anything under /api that doesn't
        exist rather than answering with HTML.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
