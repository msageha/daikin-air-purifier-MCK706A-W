# CLAUDE.md

ダイキンの加湿空気清浄機 MCK706A-W のローカル dsiot API を FastAPI でラップした REST サーバー。
API の仕様・プロパティ対応表・実機で確認した挙動は README.md に集約している。

## セットアップと検証

- `mise install`: ツールのインストール、`uv sync --locked`、git hooks (pre-commit / commit-msg) のセットアップ。旧 pre-commit (`make precommit-install`) の hook が残る clone では `mise exec -- prek install --force` で置き換える。
- `mise run test`: coverage 付き pytest。オフラインで完結し、実機には触れない。
- `mise run lint`: ruff format --check / ruff check / ty check。
- `mise exec -- prek run --all-files`: 全 hook (dprint、actionlint、hadolint、ruff、ty、gitleaks 等) を実行する。CI の `prek` job と同じ検証。
- `mise run dev`: 開発サーバー (http://127.0.0.1:8000)。接続先はリポジトリ直下の `.env` の `DAIKIN_HOST`。
- `mise run docs`: `mise.toml` の tasks を変更したあと README のタスク一覧を同期する。

## 構成

- `src/daikin/`: dsiot クライアント (FastAPI 非依存)。`protocol.py` (multireq 本文・デコーダ・PropertyTree)、`models.py`、`client.py` (アドレス・プロパティパス・wire 値・高レベル API)、`exceptions.py`。
- `src/api/`: FastAPI 層 (`routes.py` / `schemas.py` / `service.py`)。`src/main.py` が例外 → HTTP status の対応を持つ。
- `tests/`: `src` をミラーしたオフライン単体テスト。
- 新しいプロパティを公開するときは `client.py` にプロパティパスの定数と `tree.decode(...)` の 1 行、`models.py` に対応するフィールドを足す。

## 規約

- commit message は Conventional Commits (`type(scope): subject`)。commit-msg hook の commitlint が検査する。
- json / yaml / markdown / toml は dprint、python は ruff で整形する。手で整えず `prek run --all-files` に任せる。
- ruff / ty は `uv run --locked` で `uv.lock` のバージョンを使う。pre-commit 側にバージョンを持たない。
- `.gitignore` はホワイトリスト方式。新しいファイルを追跡するときは対応する `!` の行を追記する。
- ツールは `mise.toml` に exact version で pin し、変更したら `mise lock` で `mise.lock` を追従させる。Python 本体は uv が管理する。
- workflow の `uses:` は commit SHA で固定し、バージョンをコメントで併記する。
- コメント・ドキュメントは日本語で書き、技術用語・識別子は原語のまま使う。
- 実機への書き込み検証は、値を変えて読み戻したら直後に元の値へ戻す。`md.mx` の範囲外の値は送らない (範囲外を書くと `/api/status` が 502 になる。README「エラー」参照)。
