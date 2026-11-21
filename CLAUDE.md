# CLAUDE.md

ダイキンの加湿空気清浄機 MCK706A-W のローカル dsiot API を FastAPI でラップした REST サーバー。
API の仕様・プロパティ対応表・実機で確認した挙動は README.md に集約している。

## セットアップと検証

- 初回は `mise trust` でこのディレクトリの `mise.toml` を信頼してから `mise install` する。
- `mise install`: ツールのインストール、`uv sync --locked`、git hooks (pre-commit / pre-push / commit-msg / pre-merge-commit) のセットアップ。旧 pre-commit (`make precommit-install`) の hook が残る clone では `mise exec -- prek install --force` で置き換える。
- `mise run test`: coverage 付き pytest。オフラインで完結し、実機には触れない。
- `mise run format`: リポジトリ全体の import の並べ替えと ruff format。commit 時の `ruff-isort` / `ruff-format` hook は commit するファイルだけを整形する。
- `mise run lint`: ruff check / ruff format --check / lint-imports / ty check / pyright。pre-commit の `lint` hook も同じ task を呼ぶ。
- `mise run pre-commit`: pre-commit stage の hook (dprint、actionlint、zizmor、hadolint、typos、ruff の整形 / lint、gitleaks 等) を全追跡ファイルに実行する。整形する hook は全追跡ファイルを書き換えうるので、実行後は差分を確かめる。Python だけの検証は `mise run lint` と `mise run test` で足りる。CI の `prek` job の `Run prek` step と同じ検証 (commit-msg stage の commitlint は含まず、zizmor の online audit は token があるときだけ走る)。`test` hook は pre-push で `mise run test` を実行する。
- commit 時の hook (dprint・ruff の整形・README のタスク一覧の同期) がファイルを書き換えると、その commit は失敗する。書き換えた差分を見直し、stage し直してから commit し直す。`.pre-commit-config.yaml` を変えたら `mise exec -- prek install` で hook を登録し直す。
- `mise run dev`: 開発サーバー (http://127.0.0.1:8000)。接続先は環境変数 `DAIKIN_HOST` (必須。アプリは `.env` を読まない) で、git 管理外の `mise.local.toml` の `[env]` かシェルから渡す。
- `mise run docs`: `mise.toml` の tasks を変更したあと README のタスク一覧を同期する。

## 構成

- `src/daikin/`: dsiot クライアント (FastAPI 非依存)。`protocol.py` (multireq 本文・デコーダ・PropertyTree)、`models.py`、`client.py` (アドレス・プロパティパス・wire 値・高レベル API)、`exceptions.py`。
- `src/api/`: FastAPI 層 (`routes.py` / `schemas.py` / `service.py`)。`src/main.py` が例外 → HTTP status の対応を持つ。
- `tests/`: `src` をミラーしたオフライン単体テスト。
- 層の依存は `pyproject.toml` の `[tool.importlinter]` が `api`・`daikin` の中を検査する (`src` 直下の `main.py`・`settings.py` 自身の import は対象外で、`main.py` は fastapi を import する)。`daikin` は `api`・`main`・`settings` に依存しない。層は上から `api`: `routes` → `schemas` | `service`、`daikin`: `client` → `protocol` | `models` → `exceptions` で、上の層は下の層を (間の層を飛ばしても) import でき、下から上と `|` で並べた同じ層どうしは import できない。`api`・`daikin` の中で fastapi を直接 import できるのは `api`、requests は `daikin.client` だけ。`api`・`daikin` の直下にモジュールを足したら、`exhaustive = true` の契約の `layers` にも足す。
- 新しいプロパティを公開するときは `client.py` にプロパティパスの定数と `tree.decode(パス, decoder=...)` の 1 行、`models.py` に対応するフィールドを足す。

## 規約

- commit message は Conventional Commits (`type(scope): subject`)。commit-msg hook の commitlint が検査する。
- json / yaml / markdown / toml / Dockerfile は dprint、python は ruff で整形する。手で整えず、`mise run format` (python) と `mise run pre-commit` (全種類) に任せる。
- Python は 3.14 以上。ruff・ty・pyright は strict に設定している (例: 2 引数目以降は keyword-only、相対 import・`from __future__ import annotations`・`src.<module>` 経由の import は禁止)。
- 実行する Python の版を上げるときは `.python-version` と `Dockerfile` の `ARG PYTHON_VERSION` を同じ値にする (片方だけが上がらないよう、`renovate.json` で両方を Renovate の対象外にしている)。対応する下限を上げるときは `pyproject.toml` の `requires-python` と `[tool.pyright]` の `pythonVersion` も合わせる。
- lint の指摘は原因を直し、設定を緩めて通さない。原因を直せない誤検知だけを除外し、理由を添える: python は規則名付きの `# noqa: <code>`・`# ty: ignore[<rule>]`・`# pyright: ignore[<rule>]` (`# type: ignore` は ty・pyright とも無効)。hadolint は `.hadolint.yaml` の `ignored` (Dockerfile 内の `# hadolint ignore=` は無効)、typos の誤検知は `typos.toml`。zizmor は除外を受け付けないので、finding は指摘されたファイル (workflow か `.pre-commit-config.yaml`) を直して解消する。Dockerfile の `LABEL` を足すときは `.hadolint.yaml` の `label-schema` にも足す (schema に無い label は拒否される)。
- ruff / ty / import-linter は `uv run --locked` で `uv.lock` のバージョンを、pyright は `mise.toml` の版を使う。pre-commit 側にバージョンを持たず、hook は mise の task か `mise exec -- uv run --locked` を呼ぶ。
- main は PR 必須で、main への commit と merge commit は `no-commit-to-branch` hook が止める。作業はブランチで行う。
- Python の依存の取得元は、`pyproject.toml` の `[[tool.uv.index]]` で既定の index にした `https://pypi.flatt.tech/simple/` に固定している。既定の index を差し替える `UV_DEFAULT_INDEX` と、追加の index (`UV_INDEX`・`UV_EXTRA_INDEX_URL`・`--index`・ユーザー設定の `[[index]]`) は、この宣言より先に使われて `uv.lock` の取得元と食い違うので使わない。
- `.gitignore` はホワイトリスト方式。新しいファイルが無視される (`git check-ignore -v <path>` が一致を返す) ときは、対応する `!` の行を追記する。`src/` と `tests/` の下は許可済み。
- ツールは `mise.toml` に exact version で pin し、変更したら `mise lock` で `mise.lock` を追従させる。npm: backend のツール (pyright) は `mise.lock` が `.mise/locks/` の下の依存の lock を digest で参照するので、その差分も同じ commit に含め、手で編集しない。Python 本体は `.python-version` (3.14) を uv が取得する。
- workflow の `uses:` は commit SHA で固定し、バージョンをコメントで併記する。
- コメント・ドキュメントは日本語で書き、技術用語・識別子は原語のまま使う。
- 実機への書き込み検証は、値を変えて読み戻したら直後に元の値へ戻す。`md.mx` の範囲外の値は送らない (本体は範囲外の値も拒否せず保存し、このサーバーが復号できない値 (運転切替 `01`、コード 11 以上のコース等) だと以降 `/api/status` が 502 になる。README「エラー」参照)。
