# Slack DM 通知サービス — 設計ドキュメント (v1)

- 日付: 2026-06-05
- ステータス: 承認済み（実装計画へ）

## 1. 目的

エンドポイントへのリクエスト（`user`, `pass`, `notify_id`, `param` を含む）を受けると、
対応する登録ユーザーの Slack DM に通知を送るサービス。複数ユーザーを登録でき、
各ユーザーは複数の「通知タイプ（テンプレート）」を管理 UI から作成・編集できる。

## 2. 主要な決定事項

| 論点 | 決定 |
|---|---|
| DM 送信方式 | Slack Bot Token + Web API（`chat.postMessage`、channel = ユーザーの member ID）。Incoming Webhook は宛先固定のため不採用 |
| `notify_id` の意味 | 通知タイプ（テンプレート）の識別子。1 ユーザーが複数の通知タイプを持てる |
| `param` の扱い | テンプレートの穴埋め（`{key}` を `param[key]` で置換） |
| v1 スコープ | API + 管理 UI 両方 |
| 技術スタック | Python + FastAPI、SQLite + SQLAlchemy、Jinja2、slack_sdk、passlib(bcrypt) |
| `/notify` 認証 | リクエスト毎に user/pass を送信（要望どおり）。HTTPS 前提。API トークン化は YAGNI で見送り |
| ユーザー登録 | セルフサービス（`/register`）。管理者限定にはしない |

## 3. 全体アーキテクチャ

```
[クライアント] ──POST /notify {user, pass, notify_id, param}──▶ [FastAPI]
                                                                  │
[ブラウザ] ──ログイン/通知タイプ管理(UI)──▶ [FastAPI + Jinja2]    │
                                                                  ▼
                                              認証 → テンプレ取得 → 穴埋め
                                                                  │
                                                                  ▼
                                        slack_sdk WebClient.chat_postMessage
                                              (channel = ユーザーの member ID)
                                                                  ▼
                                                          [Slack DM]
```

- 永続化は SQLite + SQLAlchemy（後で Postgres へ差し替え可能な構成）
- Slack 送信は Bot Token を 1 つ（環境変数 `SLACK_BOT_TOKEN`）保持
- UI は Jinja2 テンプレート + セッション Cookie 認証（SPA は YAGNI）

## 4. データモデル

### User
| カラム | 型 | 説明 |
|---|---|---|
| id | int PK | |
| username | str unique | ログイン / `/notify` の `user` に対応 |
| password_hash | str | bcrypt(passlib)。`pass` を検証 |
| slack_member_id | str | DM 送信先の Slack member ID（例 `U01ABC...`） |
| created_at | datetime | |

### NotificationType（通知タイプ＝テンプレート）
| カラム | 型 | 説明 |
|---|---|---|
| id | int PK | |
| user_id | int FK → User | |
| notify_id | str | そのユーザー内で一意の識別子（リクエストの `notify_id`） |
| name | str | 表示名 |
| template | str | 本文テンプレート。`{service} のデプロイが {status} で完了` のような穴埋め形式 |
| created_at | datetime | |

制約: `(user_id, notify_id)` に複合ユニーク制約。

## 5. モジュール構成（責務分離）

```
app/
  main.py          # FastAPI アプリ・ルート登録
  config.py        # 設定（SLACK_BOT_TOKEN, SECRET_KEY, DB URL）
  db.py            # engine, session
  models.py        # User, NotificationType
  auth.py          # パスワード hash/検証, ユーザー認証, UI セッション
  slack.py         # send_dm(member_id, text) ラッパ（テスト時 mock 可）
  templating.py    # render(template, param): 穴埋め + 不足変数の検証, 変数抽出
  routes/
    notify.py      # POST /notify
    auth_ui.py     # /register, /login, /logout
    types_ui.py    # 通知タイプ CRUD (UI)
  templates/       # Jinja2 (login, register, dashboard, type_form)
tests/
```

各モジュールの責務:
- `slack.py`: Slack への副作用を 1 箇所に閉じ込め、テストで差し替え可能にする
- `templating.py`: 純粋関数。テンプレ文字列と param 辞書から本文を生成し、不足変数を検出
- `auth.py`: 認証ロジックを集約（`/notify` の user/pass 検証と UI セッションの両方）

## 6. API / UI 仕様

### 通知エンドポイント
```
POST /notify
Content-Type: application/json
{ "user": "alice", "pass": "secret", "notify_id": "deploy_done",
  "param": { "service": "api", "status": "ok" } }
```
処理: 認証 → `(user_id, notify_id)` でテンプレ取得 → `param` で穴埋め → 当該ユーザーの DM へ送信。

成功レスポンス: `200 {"ok": true, "ts": "<slack message ts>"}`

### 管理 UI（Jinja2 + セッション Cookie）
| パス | メソッド | 機能 |
|---|---|---|
| `/register` | GET, POST | ユーザー登録（username, password, slack_member_id） |
| `/login` | GET, POST | ログイン |
| `/logout` | POST | ログアウト |
| `/` | GET | ダッシュボード（自分の通知タイプ一覧） |
| `/types/new` | GET | 作成フォーム |
| `/types` | POST | 通知タイプ作成（name, notify_id, template） |
| `/types/{id}/edit` | GET | 編集フォーム |
| `/types/{id}` | POST | 編集保存 |
| `/types/{id}/delete` | POST | 削除 |
| `/types/{id}/test` | POST | テスト送信（自分の DM へ） |

UI 認可: 各 `/types/*` 操作はログインユーザー自身が所有する NotificationType のみ対象（他人の id を操作不可）。

## 7. テンプレート穴埋め（templating.py）

- `template` 内の `{key}` を `param[key]` で置換。`str.format_map` をベースにした安全な実装
  （`{{` `}}` のエスケープを尊重、未知キーは `KeyError` を捕捉して不足として扱う）
- テンプレ作成・編集時に必要変数を抽出（保存または都度抽出）し、`/notify` 時に `param` の過不足を検証
- 不足キーは `400` で「どの変数が足りないか（`missing`）」を返す
- 余剰キーは無視（警告ログのみ）

## 8. エラー処理（構造化 JSON）

| 状況 | ステータス | レスポンス例 |
|---|---|---|
| 認証失敗 | 401 | `{"ok": false, "error": "invalid_credentials"}` |
| notify_id 不明 | 404 | `{"ok": false, "error": "notify_type_not_found"}` |
| param 不足 | 400 | `{"ok": false, "error": "missing_params", "missing": ["status"]}` |
| Slack API 失敗 | 502 | `{"ok": false, "error": "slack_error", "detail": "..."}` |
| リクエスト不正（JSON 不備等） | 422 | FastAPI 標準のバリデーションエラー |

セキュリティ:
- パスワードは bcrypt ハッシュで保存。`pass` は平文比較せず verify
- `/notify` は毎回 user/pass を送信するため HTTPS 前提（README に明記）
- UI セッションは署名付き Cookie（`SECRET_KEY`）

## 9. テスト方針（TDD, 目標カバレッジ 80%+）

- Unit:
  - `templating`: 穴埋め正常系、不足変数検出、余剰キー無視、`{{}}` エスケープ
  - `auth`: hash/verify、認証成功・失敗
  - `slack`: send_dm が WebClient を正しく呼ぶ（mock）
- Integration（FastAPI TestClient + Slack を mock）:
  - `/notify` 正常系 / 401 / 404 / 400 / 502
  - 登録 → ログイン → タイプ作成 → `/notify` の一連フロー
  - 他人の通知タイプを操作できないことの確認

## 10. 環境変数 / 設定

| 変数 | 説明 |
|---|---|
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token（`xoxb-...`）。要スコープ: `chat:write`, `im:write` |
| `SECRET_KEY` | UI セッション Cookie 署名用 |
| `DATABASE_URL` | 既定 `sqlite:///./slack_noti.db` |

## 11. スコープ外（将来）

- API トークンによる `/notify` 認証
- レート制限
- Block Kit によるリッチメッセージ
- Postgres への移行（構成上は容易）
- 通知履歴の保存・監査ログ
