import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from slack_sdk import WebClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import NotificationType
from app.slack import SlackError, get_slack_client, send_dm
from app.templating import extract_variables, render

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _build_type_view(origin: str, username: str, nt: NotificationType) -> dict:
    """ダッシュボード表示用に、変数一覧と curl / Python サンプルを生成する。"""
    variables = extract_variables(nt.template)
    payload = {
        "user": username,
        "pass": "YOUR_PASSWORD",
        "notify_id": nt.notify_id,
        "param": {v: f"<{v}>" for v in variables},
    }
    body = json.dumps(payload, ensure_ascii=False)
    curl = (
        f"curl -X POST {origin}/notify \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f"  -d '{body}'"
    )
    py_payload = json.dumps(payload, ensure_ascii=False, indent=4).replace("\n", "\n    ")
    python = (
        "import requests\n\n"
        f'resp = requests.post(\n    "{origin}/notify",\n    json={py_payload},\n)\n'
        "print(resp.status_code, resp.json())"
    )
    return {
        "id": nt.id,
        "name": nt.name,
        "notify_id": nt.notify_id,
        "template": nt.template,
        "variables": variables,
        "curl": curl,
        "python": python,
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    rows = (
        db.execute(
            select(NotificationType).where(NotificationType.user_id == user.id)
        )
        .scalars()
        .all()
    )
    origin = str(request.base_url).rstrip("/")
    types = [_build_type_view(origin, user.username, nt) for nt in rows]
    return templates.TemplateResponse(
        request, "dashboard.html", {"user": user, "types": types}
    )


@router.get("/types/new", response_class=HTMLResponse)
def new_type_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "type_form.html", {"type": None, "error": None}
    )


@router.post("/types")
def create_type(
    request: Request,
    name: str = Form(...),
    notify_id: str = Form(...),
    template: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    existing = db.execute(
        select(NotificationType).where(
            NotificationType.user_id == user.id,
            NotificationType.notify_id == notify_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "type_form.html",
            {"type": None, "error": "notify_id already exists"},
            status_code=400,
        )
    nt = NotificationType(
        user_id=user.id, name=name, notify_id=notify_id, template=template
    )
    db.add(nt)
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/types/{type_id}/edit", response_class=HTMLResponse)
def edit_type_form(type_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    nt = db.get(NotificationType, type_id)
    if nt is None or nt.user_id != user.id:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "type_form.html", {"type": nt, "error": None}
    )


@router.post("/types/{type_id}")
def update_type(
    type_id: int,
    request: Request,
    name: str = Form(...),
    notify_id: str = Form(...),
    template: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    nt = db.get(NotificationType, type_id)
    if nt is None or nt.user_id != user.id:
        return RedirectResponse("/", status_code=303)
    nt.name = name
    nt.notify_id = notify_id
    nt.template = template
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/types/{type_id}/delete")
def delete_type(type_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    nt = db.get(NotificationType, type_id)
    if nt is not None and nt.user_id == user.id:
        db.delete(nt)
        db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/types/{type_id}/test")
def test_type(
    type_id: int,
    request: Request,
    db: Session = Depends(get_db),
    client: WebClient = Depends(get_slack_client),
):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    nt = db.get(NotificationType, type_id)
    if nt is None or nt.user_id != user.id:
        return RedirectResponse("/", status_code=303)
    sample = {name: f"<{name}>" for name in extract_variables(nt.template)}
    text = render(nt.template, sample).text
    try:
        send_dm(client, user.slack_member_id, f"[test] {text}")
    except SlackError:
        pass
    return RedirectResponse("/", status_code=303)
