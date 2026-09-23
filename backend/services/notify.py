"""
Telling people what happened.

In-app only, and deliberately. Email means a provider, deliverability
and spam folders; push means VAPID keys, permission prompts and a real
service worker where this application has an empty one on purpose. A
bell with a count answers the question people actually have — "is there
anything new for me?" — and costs a table.

Written at the moment the thing happens rather than worked out on
demand, because "what has changed since you last looked" cannot be read
off the current state: a released mark looks the same whether it was
released a minute ago or last term.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from models import Notification

logger = logging.getLogger(__name__)


def notify(
    db: Session,
    user_id: str | None,
    kind: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification | None:
    """
    Add one notification. Does not commit — it joins whatever
    transaction the caller is already in, so a notification cannot
    survive an action that was rolled back.

    A missing user is not an error: a teacher uploading a stack of
    scripts has nobody to tell, and that is a normal thing to do rather
    than a fault worth raising in the middle of an upload.
    """
    if not user_id:
        return None
    note = Notification(user_id=user_id, kind=kind, title=title, body=body, link=link)
    db.add(note)
    return note


def notify_many(db: Session, user_ids: list[str], **kwargs) -> int:
    """The same, for everyone in a list. Duplicates are ignored."""
    seen: set[str] = set()
    for user_id in user_ids:
        if user_id and user_id not in seen:
            seen.add(user_id)
            notify(db, user_id, **kwargs)
    return len(seen)
