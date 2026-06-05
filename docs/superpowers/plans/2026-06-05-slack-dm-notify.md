# Slack DM 通知サービス Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** エンドポイントへのリクエスト（user, pass, notify_id, param）を受け、認証済みユーザーの Slack DM にテンプレ穴埋め通知を送る FastAPI サービスと、通知タイプを管理する Web UI を作る。

**Architecture:** FastAPI 単一アプリ。`/notify` は JSON API、管理画面は Jinja2 + セッション Cookie。永続化は SQLAlchemy + SQLite。Slack 送信は bot token を使った `chat.postMessage`（channel = ユーザーの member ID）。副作用（Slack・DB）は依存性注入で差し替え可能にし、TestClient + mock でテストする。

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, Jinja2, slack_sdk, passlib[bcrypt], Starlette SessionMiddleware, pytest, pytest-cov, httpx (TestClient)。

設計の出典: `docs/superpowers/specs/2026-06-05-slack-dm-notify-design.md`

---

## File Structure

```
requirements.txt        # 依存パッケージ
.env.example            # 必要な環境変数の見本
app/
  __init__.py
  config.py             # 環境変数からの設定読み込み
  db.py                 # Base, engine, SessionLocal, get_db
  models.py             # User, NotificationType
  security.py           # hash_password, verify_password (bcrypt)
  templating.py         # extract_variables, render
  slack.py              # get_slack_client, send_dm, SlackError
  auth.py               # authenticate_user, get_current_user
  schemas.py            # NotifyRequest (Pydantic)
  main.py               # create_app(), lifespan, ルート登録
  routes/
    __init__.py
    notify.py           # POST /notify
    auth_ui.py          # /register, /login, /logout
    types_ui.py         # 通知タイプ CRUD + テスト送信
  templates/
    base.html
    register.html
    login.html
    dashboard.html
    type_form.html
tests/
  conftest.py           # engine/db/client/slack fixtures
  test_security.py
  test_templating.py
  test_slack.py
  test_auth.py
  test_notify.py
  test_auth_ui.py
  test_types_ui.py
README.md
```

---

## Task 1: プロジェクト雛形と設定

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py` (空ファイル)
- Create: `app/config.py`
- Create: `tests/__init__.py` (空ファイル)
- Test: `tests/test_config.py`

- [ ] **Step 1: 依存パッケージを記述**

`requirements.txt`:
```
fastapi>=0.110
uvicorn[standard]>=0.29
sqlalchemy>=2.0
jinja2>=3.1
python-multipart>=0.0.9
passlib[bcrypt]>=1.7
slack_sdk>=3.27
itsdangerous>=2.1
pydantic>=2.6
httpx>=0.27
pytest>=8.0
pytest-cov>=5.0
```

- [ ] **Step 2: 仮想環境を作り依存をインストール**

Run:
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```
Expected: すべてのパッケージが正常にインストールされる。

- [ ] **Step 3: 空の `app/__init__.py` と `tests/__init__.py` を作成**

両ファイルとも空でよい（パッケージ化のため）。

- [ ] **Step 4: 失敗するテストを書く**

`tests/test_config.py`:
```python
from app.config import get_settings


def test_get_settings_reads_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SECRET_KEY", "topsecret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./x.db")
    s = get_settings()
    assert s.slack_bot_token == "xoxb-test"
    assert s.secret_key == "topsecret"
    assert s.database_url == "sqlite:///./x.db"


def test_get_settings_has_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = get_settings()
    assert s.database_url == "sqlite:///./slack_noti.db"
```

- [ ] **Step 5: テストが失敗することを確認**

Run: `. .venv/bin/activate && pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.config'`）

- [ ] **Step 6: 最小実装**

`app/config.py`:
```python
import os
from dataclasses import dataclass


@dataclass
class Settings:
    slack_bot_token: str
    secret_key: str
    database_url: str


def get_settings() -> Settings:
    return Settings(
        slack_bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./slack_noti.db"),
    )
```

- [ ] **Step 7: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_config.py -v`
Expected: PASS（2 passed）

- [ ] **Step 8: コミット**

```bash
git add requirements.txt app/__init__.py app/config.py tests/__init__.py tests/test_config.py
git commit -m "feat: project scaffolding and settings"
```

---

## Task 2: DB とモデル

**Files:**
- Create: `app/db.py`
- Create: `app/models.py`
- Create: `tests/conftest.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: DB 基盤を実装**

`app/db.py`:
```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

Base = declarative_base()

_settings = get_settings()
_connect_args = (
    {"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {}
)
engine = create_engine(_settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: モデルを実装**

`app/models.py`:
```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    slack_member_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    notification_types: Mapped[list["NotificationType"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class NotificationType(Base):
    __tablename__ = "notification_types"
    __table_args__ = (
        UniqueConstraint("user_id", "notify_id", name="uq_user_notify_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    notify_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    template: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="notification_types")
```

- [ ] **Step 3: テスト用 fixture を作成**

`tests/conftest.py`:
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (モデルを Base.metadata に登録)
from app.db import Base


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def TestingSession(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def db(TestingSession):
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 4: 失敗するテストを書く**

`tests/test_models.py`:
```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import NotificationType, User


def test_create_user_and_notification_type(db):
    user = User(username="alice", password_hash="h", slack_member_id="U1")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.id is not None
    assert user.created_at is not None

    nt = NotificationType(
        user_id=user.id, notify_id="deploy", name="Deploy", template="{x}"
    )
    db.add(nt)
    db.commit()
    assert nt.id is not None


def test_username_is_unique(db):
    db.add(User(username="alice", password_hash="h", slack_member_id="U1"))
    db.commit()
    db.add(User(username="alice", password_hash="h2", slack_member_id="U2"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_notify_id_unique_per_user(db):
    user = User(username="alice", password_hash="h", slack_member_id="U1")
    db.add(user)
    db.commit()
    db.add(NotificationType(user_id=user.id, notify_id="d", name="A", template="x"))
    db.commit()
    db.add(NotificationType(user_id=user.id, notify_id="d", name="B", template="y"))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 5: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_models.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: コミット**

```bash
git add app/db.py app/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: database models for users and notification types"
```

---

## Task 3: パスワードハッシュ

**Files:**
- Create: `app/security.py`
- Test: `tests/test_security.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_security.py`:
```python
from app.security import hash_password, verify_password


def test_hash_then_verify_succeeds():
    h = hash_password("secret")
    assert h != "secret"
    assert verify_password("secret", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("secret")
    assert verify_password("wrong", h) is False
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `. .venv/bin/activate && pytest tests/test_security.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.security'`）

- [ ] **Step 3: 最小実装**

`app/security.py`:
```python
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_security.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: コミット**

```bash
git add app/security.py tests/test_security.py
git commit -m "feat: password hashing with bcrypt"
```

---

## Task 4: テンプレート穴埋め

**Files:**
- Create: `app/templating.py`
- Test: `tests/test_templating.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_templating.py`:
```python
from app.templating import extract_variables, render


def test_extract_variables_returns_names_in_order():
    assert extract_variables("{service} deploy {status}") == ["service", "status"]


def test_extract_variables_ignores_escaped_braces():
    assert extract_variables("literal {{not_a_var}} {real}") == ["real"]


def test_extract_variables_dedupes():
    assert extract_variables("{a} {a} {b}") == ["a", "b"]


def test_render_fills_placeholders():
    result = render("{service} deploy {status}", {"service": "api", "status": "ok"})
    assert result.text == "api deploy ok"
    assert result.missing == []


def test_render_reports_missing_keys():
    result = render("{service} deploy {status}", {"service": "api"})
    assert result.text == ""
    assert result.missing == ["status"]


def test_render_ignores_extra_keys():
    result = render("hello {name}", {"name": "bob", "extra": "x"})
    assert result.text == "hello bob"
    assert result.missing == []


def test_render_keeps_escaped_braces_literal():
    result = render("use {{braces}} and {name}", {"name": "bob"})
    assert result.text == "use {braces} and bob"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `. .venv/bin/activate && pytest tests/test_templating.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.templating'`）

- [ ] **Step 3: 最小実装**

`app/templating.py`:
```python
import logging
import string
from dataclasses import dataclass

_formatter = string.Formatter()
_logger = logging.getLogger(__name__)


@dataclass
class RenderResult:
    text: str
    missing: list[str]


def extract_variables(template: str) -> list[str]:
    names: list[str] = []
    for _literal, field_name, _spec, _conv in _formatter.parse(template):
        if not field_name:
            continue
        base = field_name.split(".")[0].split("[")[0]
        if base and base not in names:
            names.append(base)
    return names


def render(template: str, param: dict) -> RenderResult:
    required = extract_variables(template)
    missing = [name for name in required if name not in param]
    if missing:
        return RenderResult(text="", missing=missing)
    extra = [key for key in param if key not in required]
    if extra:
        _logger.warning("render: ignoring extra param keys: %s", extra)
    try:
        text = template.format_map(param)
    except (KeyError, IndexError, AttributeError) as exc:
        # ドット/添字付きフィールドなど format 時に解決できなかったケースは
        # 500 を返さず「不足」として 400 経路に寄せる（spec §7 の KeyError=不足の意図）。
        _logger.warning("render: failed to format template: %s", exc)
        return RenderResult(text="", missing=[str(exc)])
    return RenderResult(text=text, missing=[])
```

- [ ] **Step 4: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_templating.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: コミット**

```bash
git add app/templating.py tests/test_templating.py
git commit -m "feat: template rendering with missing-variable detection"
```

---

## Task 5: Slack 送信ラッパ

**Files:**
- Create: `app/slack.py`
- Test: `tests/test_slack.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_slack.py`:
```python
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from app.slack import SlackError, send_dm


def test_send_dm_posts_message_and_returns_ts():
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "111.222"}
    ts = send_dm(client, "U123", "hello")
    client.chat_postMessage.assert_called_once_with(channel="U123", text="hello")
    assert ts == "111.222"


def test_send_dm_wraps_slack_api_error():
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError("boom", response=MagicMock())
    with pytest.raises(SlackError):
        send_dm(client, "U123", "hello")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `. .venv/bin/activate && pytest tests/test_slack.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.slack'`）

- [ ] **Step 3: 最小実装**

`app/slack.py`:
```python
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import get_settings


class SlackError(Exception):
    pass


def get_slack_client() -> WebClient:
    return WebClient(token=get_settings().slack_bot_token)


def send_dm(client: WebClient, member_id: str, text: str) -> str:
    try:
        response = client.chat_postMessage(channel=member_id, text=text)
    except SlackApiError as exc:
        raise SlackError(str(exc)) from exc
    return response["ts"]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_slack.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: コミット**

```bash
git add app/slack.py tests/test_slack.py
git commit -m "feat: slack DM sender wrapper"
```

---

## Task 6: 認証ロジック

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_auth.py`

注: `get_current_user`（UI セッション用）も同じファイルに実装するが、テストは `authenticate_user` のみ（`get_current_user` は Task 8 の UI 統合テストで検証）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_auth.py`:
```python
from app.auth import authenticate_user
from app.models import User
from app.security import hash_password


def _make_user(db):
    user = User(
        username="alice",
        password_hash=hash_password("secret"),
        slack_member_id="U1",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_authenticate_user_success(db):
    _make_user(db)
    user = authenticate_user(db, "alice", "secret")
    assert user is not None
    assert user.username == "alice"


def test_authenticate_user_wrong_password(db):
    _make_user(db)
    assert authenticate_user(db, "alice", "wrong") is None


def test_authenticate_user_unknown_username(db):
    assert authenticate_user(db, "nobody", "secret") is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `. .venv/bin/activate && pytest tests/test_auth.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.auth'`）

- [ ] **Step 3: 最小実装**

`app/auth.py`:
```python
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import verify_password


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_auth.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: コミット**

```bash
git add app/auth.py tests/test_auth.py
git commit -m "feat: user authentication and current-user helpers"
```

---

## Task 7: /notify エンドポイントとアプリ本体

**Files:**
- Create: `app/schemas.py`
- Create: `app/routes/__init__.py` (空ファイル)
- Create: `app/routes/notify.py`
- Create: `app/routes/auth_ui.py`（最小プレースホルダ）
- Create: `app/routes/types_ui.py`（最小プレースホルダ）
- Create: `app/main.py`
- Modify: `tests/conftest.py`（`slack_mock` と `client` fixture を追加）
- Test: `tests/test_notify.py`

- [ ] **Step 1: Pydantic スキーマを実装**

`app/schemas.py`:
```python
from pydantic import BaseModel, ConfigDict, Field


class NotifyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user: str
    password: str = Field(alias="pass")
    notify_id: str
    param: dict = Field(default_factory=dict)
```

- [ ] **Step 2: /notify ルートを実装**

`app/routes/__init__.py`: 空ファイル。

`app/routes/notify.py`:
```python
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
```

- [ ] **Step 3: auth_ui / types_ui の最小プレースホルダを作成**

`app/routes/auth_ui.py`:
```python
from fastapi import APIRouter

router = APIRouter()
```

`app/routes/types_ui.py`:
```python
from fastapi import APIRouter

router = APIRouter()
```

（中身は Task 8・9 で実装する。ここでは `create_app()` が import できることが目的。）

- [ ] **Step 4: アプリ本体を実装**

`app/main.py`:
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401  (Base.metadata 登録)
    from app.db import Base, engine

    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Slack DM Notify", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

    from app.routes import auth_ui, notify, types_ui

    app.include_router(notify.router)
    app.include_router(auth_ui.router)
    app.include_router(types_ui.router)
    return app


app = create_app()
```

- [ ] **Step 5: conftest に client / slack_mock fixture を追加**

`tests/conftest.py` の先頭 import 群に追記:
```python
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app
from app.slack import get_slack_client
```

`tests/conftest.py` の末尾に追記:
```python
@pytest.fixture
def slack_mock():
    mock = MagicMock()
    mock.chat_postMessage.return_value = {"ts": "1234.5678"}
    return mock


@pytest.fixture
def client(TestingSession, slack_mock):
    app = create_app()

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_slack_client] = lambda: slack_mock
    return TestClient(app)
```

- [ ] **Step 6: 失敗するテストを書く**

`tests/test_notify.py`:
```python
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from app.models import NotificationType, User
from app.security import hash_password


@pytest.fixture
def seeded(db):
    user = User(
        username="alice",
        password_hash=hash_password("secret"),
        slack_member_id="U999",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        NotificationType(
            user_id=user.id,
            notify_id="deploy_done",
            name="Deploy",
            template="{service} deploy {status}",
        )
    )
    db.commit()
    return user


def test_notify_success(client, seeded, slack_mock):
    r = client.post(
        "/notify",
        json={
            "user": "alice",
            "pass": "secret",
            "notify_id": "deploy_done",
            "param": {"service": "api", "status": "ok"},
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ts": "1234.5678"}
    slack_mock.chat_postMessage.assert_called_once_with(
        channel="U999", text="api deploy ok"
    )


def test_notify_invalid_credentials(client, seeded):
    r = client.post(
        "/notify",
        json={"user": "alice", "pass": "wrong", "notify_id": "deploy_done", "param": {}},
    )
    assert r.status_code == 401
    assert r.json() == {"ok": False, "error": "invalid_credentials"}


def test_notify_unknown_notify_id(client, seeded):
    r = client.post(
        "/notify",
        json={"user": "alice", "pass": "secret", "notify_id": "nope", "param": {}},
    )
    assert r.status_code == 404
    assert r.json() == {"ok": False, "error": "notify_type_not_found"}


def test_notify_missing_params(client, seeded):
    r = client.post(
        "/notify",
        json={
            "user": "alice",
            "pass": "secret",
            "notify_id": "deploy_done",
            "param": {"service": "api"},
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "missing_params"
    assert body["missing"] == ["status"]


def test_notify_slack_error(client, seeded, slack_mock):
    slack_mock.chat_postMessage.side_effect = SlackApiError(
        "boom", response=MagicMock()
    )
    r = client.post(
        "/notify",
        json={
            "user": "alice",
            "pass": "secret",
            "notify_id": "deploy_done",
            "param": {"service": "api", "status": "ok"},
        },
    )
    assert r.status_code == 502
    assert r.json()["error"] == "slack_error"


def test_notify_malformed_request_returns_422(client):
    # 必須フィールド "pass" を欠いた不正リクエスト → Pydantic バリデーションで 422
    r = client.post("/notify", json={"user": "alice", "notify_id": "x"})
    assert r.status_code == 422
```

- [ ] **Step 7: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_notify.py -v`
Expected: PASS（6 passed）

- [ ] **Step 8: コミット**

```bash
git add app/schemas.py app/routes/__init__.py app/routes/notify.py app/routes/auth_ui.py app/routes/types_ui.py app/main.py tests/conftest.py tests/test_notify.py
git commit -m "feat: /notify endpoint with auth, templating, and slack delivery"
```

---

## Task 8: 認証 UI（登録・ログイン・ログアウト）

**Files:**
- Modify: `app/routes/auth_ui.py`（プレースホルダを本実装に差し替え）
- Create: `app/templates/base.html`
- Create: `app/templates/register.html`
- Create: `app/templates/login.html`
- Test: `tests/test_auth_ui.py`

- [ ] **Step 1: ベーステンプレートを作成**

`app/templates/base.html`:
```html
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Slack DM Notify</title>
</head>
<body>
  {% block body %}{% endblock %}
</body>
</html>
```

`app/templates/register.html`:
```html
{% extends "base.html" %}
{% block body %}
<h1>ユーザー登録</h1>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
<form method="post" action="/register">
  <p><input name="username" placeholder="username" required></p>
  <p><input name="password" type="password" placeholder="password" required></p>
  <p><input name="slack_member_id" placeholder="Slack member ID (U...)" required></p>
  <p><button type="submit">登録</button></p>
</form>
<p><a href="/login">ログインへ</a></p>
{% endblock %}
```

`app/templates/login.html`:
```html
{% extends "base.html" %}
{% block body %}
<h1>ログイン</h1>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
<form method="post" action="/login">
  <p><input name="username" placeholder="username" required></p>
  <p><input name="password" type="password" placeholder="password" required></p>
  <p><button type="submit">ログイン</button></p>
</form>
<p><a href="/register">登録へ</a></p>
{% endblock %}
```

- [ ] **Step 2: auth_ui ルートを実装**

`app/routes/auth_ui.py`（プレースホルダ全体を置き換え）:
```python
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import authenticate_user
from app.db import get_db
from app.models import User
from app.security import hash_password

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(
        "register.html", {"request": request, "error": None}
    )


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    slack_member_id: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()
    if existing is not None:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "username already taken"},
            status_code=400,
        )
    user = User(
        username=username,
        password_hash=hash_password(password),
        slack_member_id=slack_member_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": None}
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, username, password)
    if user is None:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "invalid credentials"},
            status_code=401,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
```

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_auth_ui.py`:
```python
from sqlalchemy import select

from app.models import User


def test_register_creates_user_and_redirects(client, db):
    r = client.post(
        "/register",
        data={"username": "bob", "password": "pw", "slack_member_id": "U1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    user = db.execute(select(User).where(User.username == "bob")).scalar_one()
    assert user.slack_member_id == "U1"


def test_register_duplicate_username(client):
    client.post(
        "/register",
        data={"username": "bob", "password": "pw", "slack_member_id": "U1"},
    )
    r = client.post(
        "/register",
        data={"username": "bob", "password": "pw2", "slack_member_id": "U2"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_login_success(client):
    client.post(
        "/register",
        data={"username": "bob", "password": "pw", "slack_member_id": "U1"},
    )
    client.post("/logout")
    r = client.post(
        "/login",
        data={"username": "bob", "password": "pw"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_login_invalid(client):
    r = client.post(
        "/login",
        data={"username": "ghost", "password": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 401
```

- [ ] **Step 4: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_auth_ui.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: コミット**

```bash
git add app/routes/auth_ui.py app/templates/base.html app/templates/register.html app/templates/login.html tests/test_auth_ui.py
git commit -m "feat: registration, login, and logout UI"
```

---

## Task 9: 通知タイプ管理 UI（CRUD + テスト送信）

**Files:**
- Modify: `app/routes/types_ui.py`（プレースホルダを本実装に差し替え）
- Create: `app/templates/dashboard.html`
- Create: `app/templates/type_form.html`
- Test: `tests/test_types_ui.py`

- [ ] **Step 1: テンプレートを作成**

`app/templates/dashboard.html`:
```html
{% extends "base.html" %}
{% block body %}
<h1>通知タイプ — {{ user.username }}</h1>
<form method="post" action="/logout"><button type="submit">ログアウト</button></form>
<p><a href="/types/new">+ 新規作成</a></p>
<ul>
{% for t in types %}
  <li>
    <strong>{{ t.name }}</strong>
    (notify_id: <code>{{ t.notify_id }}</code>)<br>
    <code>{{ t.template }}</code><br>
    <a href="/types/{{ t.id }}/edit">編集</a>
    <form method="post" action="/types/{{ t.id }}/delete" style="display:inline">
      <button type="submit">削除</button>
    </form>
    <form method="post" action="/types/{{ t.id }}/test" style="display:inline">
      <button type="submit">テスト送信</button>
    </form>
  </li>
{% else %}
  <li>まだ通知タイプがありません。</li>
{% endfor %}
</ul>
{% endblock %}
```

`app/templates/type_form.html`:
```html
{% extends "base.html" %}
{% block body %}
<h1>{% if type %}通知タイプを編集{% else %}通知タイプを作成{% endif %}</h1>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
<form method="post" action="{% if type %}/types/{{ type.id }}{% else %}/types{% endif %}">
  <p><input name="name" placeholder="表示名"
            value="{{ type.name if type else '' }}" required></p>
  <p><input name="notify_id" placeholder="notify_id"
            value="{{ type.notify_id if type else '' }}" required></p>
  <p><textarea name="template" rows="4" cols="50"
               placeholder="本文テンプレ 例: {service} のデプロイが {status} で完了"
               required>{{ type.template if type else '' }}</textarea></p>
  <p><button type="submit">保存</button></p>
</form>
<p><a href="/">戻る</a></p>
{% endblock %}
```

- [ ] **Step 2: types_ui ルートを実装**

`app/routes/types_ui.py`（プレースホルダ全体を置き換え）:
```python
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


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    types = (
        db.execute(
            select(NotificationType).where(NotificationType.user_id == user.id)
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "user": user, "types": types}
    )


@router.get("/types/new", response_class=HTMLResponse)
def new_type_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "type_form.html", {"request": request, "type": None, "error": None}
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
            "type_form.html",
            {"request": request, "type": None, "error": "notify_id already exists"},
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
        "type_form.html", {"request": request, "type": nt, "error": None}
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
```

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_types_ui.py`:
```python
from sqlalchemy import select

from app.models import NotificationType


def _register(client, username="alice"):
    client.post(
        "/register",
        data={"username": username, "password": "pw", "slack_member_id": "U999"},
    )


def test_dashboard_requires_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_create_type_and_appears_on_dashboard(client):
    _register(client)
    r = client.post(
        "/types",
        data={"name": "Deploy", "notify_id": "deploy_done", "template": "{x}"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    dash = client.get("/")
    assert "Deploy" in dash.text
    assert "deploy_done" in dash.text


def test_duplicate_notify_id_rejected(client):
    _register(client)
    client.post(
        "/types", data={"name": "A", "notify_id": "dup", "template": "x"}
    )
    r = client.post(
        "/types",
        data={"name": "B", "notify_id": "dup", "template": "y"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_update_type(client, db):
    _register(client)
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "x"})
    nt = db.execute(select(NotificationType)).scalars().one()
    r = client.post(
        f"/types/{nt.id}",
        data={"name": "A2", "notify_id": "a", "template": "y"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.refresh(nt)
    assert nt.name == "A2"
    assert nt.template == "y"


def test_delete_type(client, db):
    _register(client)
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "x"})
    nt = db.execute(select(NotificationType)).scalars().one()
    type_id = nt.id
    r = client.post(f"/types/{type_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    # アプリ側セッションが削除コミット済み。db セッションの identity-map に残る
    # 先読みキャッシュを破棄してから DB を再照会する（さもないと stale な行が返る）。
    db.expire_all()
    assert db.get(NotificationType, type_id) is None


def test_cannot_modify_other_users_type(client, db):
    _register(client, "alice")
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "x"})
    nt = db.execute(select(NotificationType)).scalars().one()
    client.post("/logout")
    _register(client, "bob")
    r = client.post(
        f"/types/{nt.id}",
        data={"name": "hacked", "notify_id": "a", "template": "z"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    db.refresh(nt)
    assert nt.name == "A"


def test_test_send_invokes_slack(client, db, slack_mock):
    _register(client)
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "hi {who}"})
    nt = db.execute(select(NotificationType)).scalars().one()
    r = client.post(f"/types/{nt.id}/test", follow_redirects=False)
    assert r.status_code == 303
    assert slack_mock.chat_postMessage.called
    _, kwargs = slack_mock.chat_postMessage.call_args
    assert kwargs["channel"] == "U999"
    assert kwargs["text"] == "[test] hi <who>"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `. .venv/bin/activate && pytest tests/test_types_ui.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: コミット**

```bash
git add app/routes/types_ui.py app/templates/dashboard.html app/templates/type_form.html tests/test_types_ui.py
git commit -m "feat: notification type CRUD UI with ownership checks and test send"
```

---

## Task 10: ドキュメントと全体検証

**Files:**
- Create: `.env.example`
- Create: `README.md`

- [ ] **Step 1: .env.example を作成**

`.env.example`:
```
# Slack Bot User OAuth Token (xoxb-...). 必要スコープ: chat:write, im:write
SLACK_BOT_TOKEN=xoxb-replace-me
# セッション Cookie 署名用のランダム文字列
SECRET_KEY=change-me-to-a-random-string
# DB 接続 URL（既定は SQLite ファイル）
DATABASE_URL=sqlite:///./slack_noti.db
```

- [ ] **Step 2: README を作成**

`README.md`:
````markdown
# slack-noti

エンドポイントへのリクエストを受けて、登録ユーザーの Slack DM に通知を送るサービス。

## セットアップ

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 値を編集
```

## Slack アプリ準備

1. https://api.slack.com/apps でアプリを作成
2. OAuth & Permissions で Bot Token Scopes に `chat:write`, `im:write` を追加
3. ワークスペースにインストールし、Bot User OAuth Token (`xoxb-...`) を `SLACK_BOT_TOKEN` に設定
4. DM を受け取る各ユーザーは Slack の member ID（`U...`）を登録時に入力する

## 起動

```bash
set -a && . ./.env && set +a
uvicorn app.main:app --reload
```

- 管理画面: http://localhost:8000/register でユーザー登録 → 通知タイプを作成
- 通知送信:

```bash
curl -X POST http://localhost:8000/notify \
  -H 'Content-Type: application/json' \
  -d '{"user":"alice","pass":"secret","notify_id":"deploy_done","param":{"service":"api","status":"ok"}}'
```

## セキュリティ注意

`/notify` はリクエスト毎に user/pass を平文で送るため、本番では必ず HTTPS 経由で公開すること。

## テスト

```bash
. .venv/bin/activate
pytest --cov=app --cov-report=term-missing
```
````

- [ ] **Step 3: 全テストとカバレッジを実行**

Run: `. .venv/bin/activate && pytest --cov=app --cov-report=term-missing -v`
Expected: 全テスト PASS、`app` パッケージのカバレッジ 80% 以上。

- [ ] **Step 4: アプリが起動することを手動確認**

Run:
```bash
. .venv/bin/activate && SECRET_KEY=test SLACK_BOT_TOKEN=xoxb-dummy \
  python -c "from app.main import app; print('app import OK:', app.title)"
```
Expected: `app import OK: Slack DM Notify`

（実際の DM 送信確認には本物の `SLACK_BOT_TOKEN` と Slack member ID が必要。UI でユーザー登録→通知タイプ作成→「テスト送信」で確認する。）

- [ ] **Step 5: コミット**

```bash
git add README.md .env.example
git commit -m "docs: setup, usage, and security notes"
```

---

## Self-Review メモ

- **Spec カバレッジ**: §4 データモデル→Task 2 / §6 /notify→Task 7 / §6 管理UI→Task 8,9 / §7 テンプレ→Task 4 / §8 エラー処理→Task 7（401/404/400/502 すべてテスト済み）/ §9 テスト→各 Task の TDD / §10 環境変数→Task 1,10。
- **所有権チェック**: 他人の通知タイプを操作できないことを Task 9 `test_cannot_modify_other_users_type` で検証。
- **エラー本文形状**: `/notify` は `JSONResponse` を直接返すことで `{"ok": false, "error": ...}` の形を保証（`HTTPException` の `{"detail": ...}` ラップを回避）。
- **型・シグネチャ整合**: `render()` は全タスクで `RenderResult(text, missing)` を返す前提で統一。`send_dm(client, member_id, text)` の引数順は Task 5 定義と Task 7・9 の呼び出しで一致。`get_slack_client` / `get_db` を DI に使い、テストで `dependency_overrides` により差し替え。

## レッドチーム検証の反映（2026-06-05）

4 観点（FastAPI/Starlette・SQLAlchemy 2.0・テスト整合・spec カバレッジ）の並列レビューを実施し、経験的再現で確定した指摘を反映済み:
- **[High] 修正済**: `test_delete_type` — `db` セッションの identity-map に残る先読み行のため `db.get()` が stale を返す問題。assertion 前に `db.expire_all()` を追加。
- **[Low] 反映**: `render()` に余剰キーの警告ログ（spec §7）と format 失敗時のガード（500→400 化）を追加。
- **[Low] 反映**: `/notify` の 422（不正リクエスト）テストを追加。
- 多数の「懸念」（TestClient の lifespan 非実行・SessionMiddleware・`JSONResponse` のボディ形状・Pydantic `alias="pass"`・StaticPool による in-memory 共有・`app=create_app()` のモジュール副作用）はいずれも**正しい実装と確認され棄却**。
- 未対応（v1 任意）: UI「テスト送信」での `SlackError` 握りつぶしは UX 改善余地として残す（spec の構造化 502 は `/notify` のみ対象なので spec 違反ではない）。
```
