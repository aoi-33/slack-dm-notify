# slack-dm-notify

エンドポイントへの HTTP リクエストを受け取ると、登録ユーザーの **Slack DM** に通知を送る軽量サービスです。
通知は「テンプレート（通知タイプ）」として管理し、リクエストの `param` で穴埋めして送信します。
**複数ユーザー対応**で、各ユーザーは Web UI から自分の通知タイプを作成・編集できます。

```
  外部システム                       slack-dm-notify (FastAPI)              Slack
 ┌────────────┐   POST /notify      ┌──────────────────────┐            ┌────────┐
 │ CI / cron  │ ──────────────────▶ │ 認証(user/pass)        │            │        │
 │ スクリプト  │  {user,pass,         │   ↓                   │  Bot Token │  DM    │
 │  など       │   notify_id,param}   │ notify_id でテンプレ取得 │ ─────────▶ │  📩    │
 └────────────┘                      │   ↓ param で穴埋め      │ chat.post  │        │
                                     │   ↓                   │ Message    └────────┘
 ┌────────────┐   ブラウザ           │ Slack DM 送信           │
 │ 管理者/利用者│ ──────────────────▶ │ (UI: 通知タイプ管理)    │
 └────────────┘                      └──────────────────────┘
```

---

## 目次

- [特徴](#特徴)
- [技術スタック](#技術スタック)
- [クイックスタート](#クイックスタート)
- [Slack Bot の設定](#slack-bot-の設定)
- [起動方法（ローカル / LAN / 本番）](#起動方法ローカル--lan--本番)
- [使い方（Web UI）](#使い方web-ui)
- [API リファレンス](#api-リファレンス)
- [通知タイプとテンプレート](#通知タイプとテンプレート)
- [設定（環境変数）](#設定環境変数)
- [プロジェクト構成](#プロジェクト構成)
- [テスト](#テスト)
- [セキュリティ](#セキュリティ)
- [トラブルシューティング](#トラブルシューティング)
- [ライセンス](#ライセンス)

---

## 特徴

- 📩 **Slack DM 通知** — Bot Token + Web API（`chat.postMessage`）で、ユーザーの member ID 宛に DM を送信
- 👥 **複数ユーザー対応** — セルフサービス登録。各ユーザーは自分の通知タイプだけを管理（所有権チェック付き）
- 🧩 **テンプレート（通知タイプ）** — `{変数}` を含む本文を登録し、リクエストの `param` で穴埋め
- 🖥 **管理 Web UI** — ログイン先行のスタイリッシュな画面で、通知タイプの作成・編集・削除・テスト送信
- 📋 **テストコマンド自動生成** — 通知タイプごとに **curl / Python のサンプル**を生成し、ワンクリックでコピー（URL は閲覧中のホストで自動補完）
- ✅ **テスト済み** — 36 ケース / カバレッジ 89%（Slack はモック）

---

## 技術スタック

| 領域 | 採用 |
|---|---|
| 言語 | Python 3.11+（動作確認 3.12） |
| Web | FastAPI + Starlette（セッション Cookie） |
| テンプレート | Jinja2（管理 UI） |
| DB / ORM | SQLite + SQLAlchemy 2.0（Postgres へ差し替え可） |
| パスワード | bcrypt（ハッシュ保存） |
| Slack | slack_sdk（`chat.postMessage`） |
| テスト | pytest / pytest-cov / httpx TestClient |

---

## クイックスタート

```bash
git clone https://github.com/aoi-33/slack-dm-notify.git && cd slack-dm-notify
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env を編集（SLACK_BOT_TOKEN と SECRET_KEY を設定）
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"   # SECRET_KEY 生成の例

set -a && . ./.env && set +a
uvicorn app.main:app --reload
```

ブラウザで http://localhost:8000/ を開く → ログイン画面（初回は「新規登録」）。

---

## Slack Bot の設定

DM を送るには **Slack アプリ（Bot）** を 1 つ作り、その Bot Token をサービスに渡します。
（Incoming Webhook は宛先が固定されるため使いません。Bot Token + Web API 方式です。）

### 1. アプリを作成
1. https://api.slack.com/apps → **「Create New App」→「From scratch」**
2. App 名（例 `slack-noti`）と対象ワークスペースを選んで **Create App**

### 2. Bot のスコープを付与
1. 左メニュー **「OAuth & Permissions」**
2. **「Scopes」→「Bot Token Scopes」** に以下を追加:
   - `chat:write` … メッセージ送信（必須）
   - `im:write` … Bot から DM を開く（必須）
   - `users:read` …（任意）member ID 解決をしたい場合

### 3. インストールしてトークン取得
1. 同ページ上部 **「Install to Workspace」** → 許可
2. **「Bot User OAuth Token」**（`xoxb-...`）をコピーして `.env` の `SLACK_BOT_TOKEN` に設定

> Bot Token を使うと、Bot 側から各ユーザーへ DM を**開始**できます（ユーザーが事前に Bot へ話しかける必要はありません。同一ワークスペースのメンバーであることが条件）。

### 4. 送信先の member ID を調べる
通知を受け取る人ごとに **Slack の member ID（`U` で始まる）** が必要です。
Slack でその人のプロフィール → **「⋮」→「メンバー ID をコピー」**（例 `U08CNP1LR4P`）。
この値をユーザー登録画面の「Slack member ID」に入力します。

---

## 起動方法（ローカル / LAN / 本番）

`.env` を環境変数に読み込んでから `uvicorn` を起動します（`set -a && . ./.env && set +a`）。

### ローカルのみ
```bash
uvicorn app.main:app --reload         # http://127.0.0.1:8000
```

### LAN 内の他デバイスからアクセス
`--host 0.0.0.0` でバインドすると、同じネットワークの端末から `http://<このマシンのIP>:8000/` で開けます。
```bash
hostname -I                            # LAN IP を確認（例 192.168.x.x）
set -a && . ./.env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- ファイアウォールでポートを開ける必要がある場合: `sudo ufw allow 8000/tcp`
- バックグラウンド常駐（簡易）:
  ```bash
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
  echo $! > uvicorn.pid          # 停止は: kill "$(cat uvicorn.pid)"
  ```

### Docker / Docker Compose
`.env` を用意すれば、Docker だけで起動できます。DB はホストの `./data` に永続化されます。
```bash
cp .env.example .env        # SLACK_BOT_TOKEN / SECRET_KEY を設定
docker compose up -d --build # http://localhost:8000
```
- ログ確認: `docker compose logs -f`
- 停止: `docker compose down`（`./data/slack_noti.db` は残るのでデータは保持）
- ポート変更: `docker-compose.yml` の `ports` を `"8080:8000"` 等に変更
- DB ファイル実体は `./data/slack_noti.db`（バックアップはこのファイルをコピー）

### 本番（systemd で自動起動）
再起動後も自動で立ち上げたい場合の例（`/etc/systemd/system/slack-noti.service`）:
```ini
[Unit]
Description=slack-noti
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/slack-noti
EnvironmentFile=/path/to/slack-noti/.env
ExecStart=/path/to/slack-noti/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now slack-noti
sudo systemctl status slack-noti
```
> インターネットに公開する場合は、前段に **HTTPS リバースプロキシ（Nginx / Caddy 等）** を必ず置いてください（後述「セキュリティ」）。

---

## 使い方（Web UI）

1. **新規登録**（`/register`）: username / password / 自分の Slack member ID を入力
2. **ログイン**後、ダッシュボードで **通知タイプ**を作成
   - 表示名（例: `デプロイ完了通知`）
   - `notify_id`（例: `deploy_done`）… リクエストで指定する識別子（自分の中で一意）
   - 本文テンプレート（例: `🚀 {service} のデプロイが {status} で完了`）
3. 各通知タイプのカードで:
   - **curl / Python** のサンプルをタブ切替 → **コピー** して外部から実行
   - **テスト送信** で自分の DM に届くか即確認
   - **編集 / 削除**

---

## API リファレンス

### `POST /notify`
通知を送信するメインのエンドポイント。

リクエスト（JSON）:
```json
{
  "user": "alice",
  "pass": "your-password",
  "notify_id": "deploy_done",
  "param": { "service": "api", "status": "ok" }
}
```

| フィールド | 説明 |
|---|---|
| `user` | ユーザー名（登録時のもの） |
| `pass` | パスワード |
| `notify_id` | 送信に使う通知タイプの識別子 |
| `param` | テンプレート変数の穴埋め値（オブジェクト） |

レスポンス:

| 結果 | ステータス | ボディ |
|---|---|---|
| 成功（DM 送信） | 200 | `{"ok": true, "ts": "<message ts>"}` |
| 認証失敗 | 401 | `{"ok": false, "error": "invalid_credentials"}` |
| notify_id 不明 | 404 | `{"ok": false, "error": "notify_type_not_found"}` |
| param 不足 | 400 | `{"ok": false, "error": "missing_params", "missing": ["status"]}` |
| Slack API 失敗 | 502 | `{"ok": false, "error": "slack_error", "detail": "..."}` |
| リクエスト不正 | 422 | FastAPI 標準のバリデーションエラー |

curl の例:
```bash
curl -X POST http://localhost:8000/notify \
  -H 'Content-Type: application/json' \
  -d '{"user":"alice","pass":"your-password","notify_id":"deploy_done","param":{"service":"api","status":"ok"}}'
```

Python の例:
```python
import requests

resp = requests.post(
    "http://localhost:8000/notify",
    json={
        "user": "alice",
        "pass": "your-password",
        "notify_id": "deploy_done",
        "param": {"service": "api", "status": "ok"},
    },
)
print(resp.status_code, resp.json())
```
> ダッシュボードでは、上記が **通知タイプごとに自動生成**され、コピーできます（`param` のキーはテンプレ変数から自動で埋まります）。

### 管理 UI のルート（ブラウザ用）

| メソッド | パス | 用途 |
|---|---|---|
| GET/POST | `/register` | ユーザー登録 |
| GET/POST | `/login` | ログイン |
| POST | `/logout` | ログアウト |
| GET | `/` | ダッシュボード（自分の通知タイプ一覧） |
| GET | `/types/new` | 作成フォーム |
| POST | `/types` | 通知タイプ作成 |
| GET | `/types/{id}/edit` | 編集フォーム |
| POST | `/types/{id}` | 編集保存 |
| POST | `/types/{id}/delete` | 削除 |
| POST | `/types/{id}/test` | テスト送信（自分の DM へ） |

---

## 通知タイプとテンプレート

- 本文テンプレートには `{変数名}` を書けます（Python の `str.format` 形式）。
  - 例: `{service} のデプロイが {status} で完了` → `param={"service":"api","status":"ok"}` で穴埋め
- リテラルの波括弧は `{{` `}}` でエスケープできます。
- 送信時に `param` が**不足**していると `400 missing_params`（不足キー一覧つき）を返します。
- `param` の**余剰**キーは無視されます（警告ログのみ）。

---

## 設定（環境変数）

`.env`（`.env.example` をコピーして編集）:

| 変数 | 必須 | 説明 |
|---|---|---|
| `SLACK_BOT_TOKEN` | ✅ | Slack Bot User OAuth Token（`xoxb-...`）。スコープ `chat:write`, `im:write` |
| `SECRET_KEY` | ✅ | セッション Cookie 署名用のランダム文字列（`secrets.token_hex(32)` で生成推奨） |
| `DATABASE_URL` |   | DB 接続 URL。既定 `sqlite:///./slack_noti.db`。Postgres 例: `postgresql+psycopg://user:pass@host/db` |

---

## プロジェクト構成

```
app/
  main.py          # FastAPI アプリ生成 / lifespan(テーブル作成) / ルート登録
  config.py        # 環境変数の読み込み
  db.py            # engine, SessionLocal, get_db
  models.py        # User, NotificationType（(user_id, notify_id) 複合ユニーク）
  security.py      # bcrypt ハッシュ / 検証
  templating.py    # 変数抽出 + 穴埋め（不足検出つき）
  slack.py         # Slack DM 送信ラッパ（テストで差し替え可能）
  auth.py          # ユーザー認証 / セッションの現在ユーザー
  schemas.py       # /notify の Pydantic スキーマ
  routes/
    notify.py      # POST /notify
    auth_ui.py     # 登録 / ログイン / ログアウト
    types_ui.py    # 通知タイプ CRUD + テスト送信 + サンプル生成
  templates/       # Jinja2（base, login, register, dashboard, type_form）
tests/             # pytest 一式（unit + 統合）
docs/              # 設計ドキュメント・実装計画
requirements.txt
.env.example
```

---

## テスト

```bash
. .venv/bin/activate
pytest --cov=app --cov-report=term-missing
```
- Slack はモックするので**実トークン不要**。
- 実際に DM が届くかの通し試験は、本物の `SLACK_BOT_TOKEN` で起動し、UI の「テスト送信」または `/notify` を実行してください。

---

## セキュリティ

- パスワードは **bcrypt でハッシュ化**して保存します。
- `/notify` は**リクエスト毎に `user`/`pass` を平文で送る**設計です。
  - **信頼できる LAN 内**、または **HTTPS 経由**でのみ公開してください。
  - インターネット公開時は **HTTPS リバースプロキシ必須**（Nginx / Caddy など）。
- `.env`（実トークン）と `*.db` は `.gitignore` 済み。**トークンをコミットしないでください**。
- 将来的な強化候補: `/notify` の API トークン認証、レート制限（現状は YAGNI で未実装）。

---

## トラブルシューティング

**LAN の他端末からつながらない**
- `--host 0.0.0.0` で起動しているか確認
- ファイアウォール: `sudo ufw allow 8000/tcp`
- 端末が同じネットワークにいるか、IP（`hostname -I`）が正しいか確認

**`/notify` が 502 を返す（`detail` を確認）**

| detail | 原因と対処 |
|---|---|
| `invalid_auth` | `SLACK_BOT_TOKEN` が誤り/失効。再取得して `.env` 更新 |
| `missing_scope` | スコープ不足。`chat:write` / `im:write` を追加し再インストール |
| `channel_not_found` | member ID が誤り、または別ワークスペース。`U...` を再確認 |

**ポートを変えたい**: `uvicorn app.main:app --port 9000`

---

## ライセンス

[MIT License](LICENSE) で公開しています。
