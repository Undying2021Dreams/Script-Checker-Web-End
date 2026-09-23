"""
A person's own account: their profile, and what has happened for them.

Kept apart from `courses` because none of it is about a course. The
only thing here a person cannot change is who they are — email and role
come from Entra ID and from the deployment's teacher list, and letting
someone edit either would be letting them grant themselves a course.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Notification, User
from schemas import NotificationList, NotificationOut, ProfileUpdate, UserOut
from security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["me"])

# A face at 256px is plenty for a 40px circle on a list, and it bounds
# what a careless upload can put in the database — these rows are read
# on every page that shows a name.
AVATAR_PX = 256
MAX_AVATAR_BYTES = 8 * 1024 * 1024


def _mine(db: Session, user: User) -> User:
    """
    The signed-in person, attached to *this* request's session.

    The dependency hands back a User, but not necessarily one this
    session owns. Mutating a detached instance and committing writes
    nothing while still returning the new values, so the response looks
    right and the database never changed — the kind of failure that only
    shows up on the next page load.
    """
    return db.query(User).filter(User.id == user.id).one()


@router.get("/me", response_model=UserOut)
def read_me(user: User = Depends(get_current_user)):
    return _profile(user)


@router.patch("/me", response_model=UserOut)
def update_me(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Correct your own name or say where you study.

    The name arrives from Entra ID on first sign-in, which is whatever
    the institution put in Active Directory — often an initial and a
    surname. It is the name that appears beside every mark, so people
    are allowed to fix it.
    """
    me = _mine(db, user)
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A name cannot be blank.")
        me.display_name = name
    if body.institution is not None:
        me.institution = body.institution.strip() or None

    db.commit()
    db.refresh(me)
    return _profile(me)


@router.post("/me/avatar", response_model=UserOut)
async def set_avatar(
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Set a profile picture.

    Squared and shrunk to 256px here rather than trusting what arrives:
    a phone photograph is several megabytes and these rows are read on
    every page that shows a name.
    """
    raw = await image.read()
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "That image is too large.")

    try:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(raw))
        img = img.convert("RGB")
        # Centre crop to a square first, so a portrait photograph does
        # not come out squashed inside a circle.
        side = min(img.size)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize(
            (AVATAR_PX, AVATAR_PX), PILImage.LANCZOS
        )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
    except Exception as exc:  # noqa: BLE001 — an unreadable upload is the answer
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"That image could not be read ({exc}).")

    me = _mine(db, user)
    me.avatar = buf.getvalue()
    me.avatar_content_type = "image/jpeg"
    db.commit()
    db.refresh(me)
    return _profile(me)


@router.delete("/me/avatar", response_model=UserOut)
def clear_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = _mine(db, user)
    me.avatar = None
    me.avatar_content_type = None
    db.commit()
    db.refresh(me)
    return _profile(me)


@router.get("/users/{user_id}/avatar")
def get_avatar(user_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """
    Anyone signed in may see anyone's picture.

    It is a face beside a name in a list a teacher and their students
    already share; there is nothing here that sign-in does not already
    grant. A missing one is a 404 so the client can fall back to
    initials.
    """
    person = db.query(User).filter(User.id == user_id).first()
    if person is None or not person.avatar:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture")
    return Response(content=person.avatar, media_type=person.avatar_content_type or "image/jpeg")


@router.get("/notifications", response_model=NotificationList)
def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    unread = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .scalar()
        or 0
    )
    return NotificationList(
        items=[
            NotificationOut(
                id=n.id, kind=n.kind, title=n.title, body=n.body, link=n.link,
                read=n.read_at is not None, created_at=n.created_at,
            )
            for n in rows
        ],
        unread=unread,
    )


@router.post("/notifications/read", response_model=NotificationList)
def mark_read(
    notification_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark one as read, or all of them when no id is given.

    Only ever your own: the filter is on user_id, so an id belonging to
    someone else simply matches nothing.
    """
    from datetime import datetime, timezone

    query = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    )
    if notification_id:
        query = query.filter(Notification.id == notification_id)
    query.update({"read_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    # Called directly, so the default has to be given: FastAPI's Query
    # object is only turned into a value when it comes through a route.
    return list_notifications(limit=30, user=user, db=db)


def _profile(user: User) -> UserOut:
    from config import settings

    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        institution=user.institution,
        has_avatar=user.avatar is not None,
        # Depends on a deployment setting as well as the account, so the
        # client is told rather than left to infer it from the role.
        can_create_courses=settings.OPEN_COURSE_CREATION or user.role in ("teacher", "admin"),
    )
