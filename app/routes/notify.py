from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from slack_sdk import WebClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import authenticate_user
from app.db import get_db
from app.models import NotificationType
from app.schemas import NotifyRequest
from app.slack import SlackError, get_slack_client, send_dm
from app.templating import render

router = APIRouter()


@router.post("/notify")
def notify(
    payload: NotifyRequest,
    db: Session = Depends(get_db),
    client: WebClient = Depends(get_slack_client),
) -> JSONResponse:
    user = authenticate_user(db, payload.user, payload.password)
    if user is None:
        return JSONResponse(
            status_code=401, content={"ok": False, "error": "invalid_credentials"}
        )

    nt = db.execute(
        select(NotificationType).where(
            NotificationType.user_id == user.id,
            NotificationType.notify_id == payload.notify_id,
        )
    ).scalar_one_or_none()
    if nt is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "notify_type_not_found"},
        )

    result = render(nt.template, payload.param)
    if result.missing:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "missing_params",
                "missing": result.missing,
            },
        )

    try:
        ts = send_dm(client, user.slack_member_id, result.text)
    except SlackError as exc:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "slack_error", "detail": str(exc)},
        )

    return JSONResponse(status_code=200, content={"ok": True, "ts": ts})
