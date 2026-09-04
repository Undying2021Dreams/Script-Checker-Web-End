"""
Microsoft Entra ID authentication.

One app registration serves both the SPA (login) and the API (the scope
below, via "Expose an API"). `azure_scheme` validates the access token on
every protected request; `get_current_user` maps the validated token to (or
creates) our own `User` row, keyed by Entra's immutable `oid` claim.
"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Security, status
from fastapi_azure_auth import MultiTenantAzureAuthorizationCodeBearer
from fastapi_azure_auth.user import User as AzureUser
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User


async def _issuer(tid: str) -> str:
    # Multi-tenant + personal accounts: accept any tenant's own issuer
    # (personal Microsoft accounts carry tid "9188040d-6c67-4c5b-b112-36a304b66dab").
    # The JWT signature (checked separately, against Microsoft's published
    # keys) is what actually anchors trust here — this just confirms the
    # claimed issuer matches the claimed tenant.
    return f"https://login.microsoftonline.com/{tid}/v2.0"


azure_scheme = MultiTenantAzureAuthorizationCodeBearer(
    app_client_id=settings.AZURE_CLIENT_ID,
    scopes={f"api://{settings.AZURE_CLIENT_ID}/access_as_user": "Access Web-End API"},
    validate_iss=True,
    iss_callable=_issuer,
)


def get_current_user(
    azure_user: AzureUser = Security(azure_scheme),
    db: Session = Depends(get_db),
) -> User:
    email = (azure_user.email or azure_user.preferred_username or "").lower()

    is_configured_teacher = email in settings.teacher_emails

    user = db.query(User).filter(User.azure_oid == azure_user.oid).one_or_none()
    if user is None:
        user = User(
            azure_oid=azure_user.oid,
            email=email,
            display_name=azure_user.name or email,
            role="teacher" if is_configured_teacher else "student",
        )
        db.add(user)
    elif is_configured_teacher and user.role == "student":
        # Promote on sign-in so adding an email to TEACHER_EMAILS takes effect
        # for someone who already signed in. Deliberately one-way: it never
        # demotes, so a role granted by other means isn't clobbered by config.
        user.role = "teacher"

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    return user


def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Teacher role required")
    return user
