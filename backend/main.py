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


@api.get("/health/egress")
def egress_check():
    """
    Temporary. Reports whether this container can reach Entra's OpenID
    configuration, which is what token validation depends on.

    Added because the failure is only reproducible from inside Azure:
    the same image, run locally, fetches the document without trouble,
    so the difference is the network the replica sits on rather than
    anything shipped in the image. Returns no secrets.
    """
    import socket
    import ssl

    import certifi
    import httpx

    out: dict = {}

    host = "login.microsoftonline.com"
    try:
        out["dns"] = sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443)})
    except Exception as exc:  # noqa: BLE001 — this is the diagnosis
        out["dns"] = f"{type(exc).__name__}: {exc}"

    out["certifi_bundle"] = certifi.where()
    try:
        out["certifi_bundle_bytes"] = __import__("os").path.getsize(certifi.where())
    except Exception as exc:  # noqa: BLE001
        out["certifi_bundle_bytes"] = str(exc)

    # Which of the two trust stores works, if either.
    for label, verify in (
        ("certifi", certifi.where()),
        ("system", "/etc/ssl/certs/ca-certificates.crt"),
        ("none", False),
    ):
        try:
            r = httpx.get(
                f"https://{host}/common/v2.0/.well-known/openid-configuration",
                timeout=10,
                verify=verify,
            )
            out[f"fetch_{label}"] = f"OK {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            out[f"fetch_{label}"] = f"{type(exc).__name__}: {exc}"

    # Is it Microsoft specifically, or all outbound TLS?
    try:
        out["fetch_other_host"] = f"OK {httpx.get('https://example.com', timeout=10).status_code}"
    except Exception as exc:  # noqa: BLE001
        out["fetch_other_host"] = f"{type(exc).__name__}: {exc}"

    # What the peer actually presents, which says whether something is
    # answering in Microsoft's place.
    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert(binary_form=False) or {}
                out["peer_subject"] = str(cert.get("subject"))
                out["peer_issuer"] = str(cert.get("issuer"))
    except Exception as exc:  # noqa: BLE001
        out["peer"] = f"{type(exc).__name__}: {exc}"

    return out


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
