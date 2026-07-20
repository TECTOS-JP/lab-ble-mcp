# lab-backend-template

[lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp) 用の機器バックエンドを作るための、実行可能なテンプレートです。`lab-<protocol>-mcp` を始める際の出発点として使います。空の TODO 集ではなく、clone直後からテストできる Echo example を同梱しています。

## Echo example

- resource: `ECHO::<name>`（大文字小文字を区別し、不正形式は拒否）
- query: `GET <key>`
- write: `SET <key> <value>`
- `EchoBackend`: resourceごとに独立したメモリ状態を持つ、動作する最小実装
- `MockEchoBackend`: BEF適合テスト用の厳密な `*IDN?` / `CONF` probe を追加

```powershell
python -m pip install -e ".[dev]"
pytest -q
lab-backend serve --resource ECHO::demo --dry-run
```

実通信プロトコルへ移植するときは、入力検証を残したまま `backend.py` の状態アクセス部分をtransport呼び出しへ置き換えます。詳細は [USING_THIS_TEMPLATE.md](docs/USING_THIS_TEMPLATE.md) を参照してください。

## 3つの利用モード

### A. MCP server

```powershell
lab-backend serve --resource ECHO::device1
```

CLIは凍結された公開API `compose_server` と `run_mcp_with_control` だけでserverを構成します。

### B. Python library

```python
from lab_backend_template import EchoBackend

backend = EchoBackend(resources=["ECHO::device1"])
```

### C. lab-executor backend discovery

インストール時に entry point `lab_executor.backends: echo` が登録されます。`lab-executor serve --backends echo` または `_system.yaml` の `backends:` から選択できます。

## 安全設計（置換後も必須）

- 書き込み可能な対象は機器定義のcommandとして明示し、raw write APIを追加しないでください。
- 未知resource、未知opcode、不正な引数、未初期化keyは推測せず fail-closed で拒否します。
- readのretryとwriteのretryを分離してください。writeの自動retryは二重書き込みや二重動作を起こし得るため、既定で行わないでください。
- 各機器定義には安全側へ戻す `safe_shutdown` を必ず定義してください。
- 実機未検証の定義は `support_level: experimental` とします。`verified` は対象実機で確認済みの場合だけ使用してください。
- このEcho実装は構造のexampleであり、物理装置の安全性を保証しません。実装時は装置固有の範囲、interlock、timeout、shutdownを追加してください。

## 開発と公開

CIはPython 3.11、Ruff、BEF適合、latest release統合、lab-executor main互換smoke、buildを検証します。タグはPyPI、手動workflowは既定でTestPyPIへTrusted Publishingで公開します。テンプレート自体は公開パッケージではないため、複製後に名前とmetadataを変更するまでtagを作らないでください。

## ライセンス

MIT
