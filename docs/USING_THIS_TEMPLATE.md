# Using this template

このリポジトリを複製した後、次の6段階で `lab-<protocol>-mcp` に置き換えます。各識別子はgrepしやすいよう意図的に統一されています。

## 1. packageと配布名をrenameする

`lab_backend_template` を `lab_<protocol>_mcp` へrenameし、全import、`pyproject.toml` のwheel/sdist設定、entry pointを更新します。配布名 `lab-backend-template` を `lab-<protocol>-mcp` に置換し、project URL、CLI名、version、READMEも更新します。

## 2. resource prefixを置換する

`ECHO::` を衝突しない固有prefixへ置換します。`resource.py` で正しい形式だけを受理し、case、長さ、許容文字、port/addressの範囲を明示して、曖昧な入力をfail-closedで拒否します。`discovery.py` の `BackendRegistration.prefixes` とroutingテストも同時に更新します。

## 3. protocol実装を置換する

`wire.py` にcommand grammarとencode/decode、`resource.py` に接続先grammar、`backend.py` に実transportを実装します。validationは接続より先に行い、query/write経路を分離します。writeを暗黙retryしないこと、timeoutと通信エラーを安定したbackend errorへ変換すること、`close()`を同期・冪等・例外なしにすることを維持します。`mock_backend.py` は実transportから独立させ、resourceごとの状態分離とexactなBEF probeだけを提供します。

## 4. instrument definitionsを追加する

`builtin_instruments/` のexampleを対象装置のmanualに基づいて置換します。書き込みcommandと全parameter rangeを明示し、raw write commandを公開しません。各定義に `safe_shutdown` を必ず設けます。実機未検証なら `support_level: experimental`、mock/限定検証なら事実に合うlevel、`verified` は対象実機確認済みの場合のみ使用します。

## 5. 適合テストを維持する

`pytest -q`、`ruff check src tests`、`ruff format --check src tests` をgreenに保ちます。最低限、BEF conformance、wire/resource fail-closed、query/write分離、resource state分離、entry point discovery、CLI dry-run、CompositeBackend routing、instrument schemaと安全宣言を対象protocolへ合わせて更新します。

## 6. TestPyPIからPyPIへ公開する

repository environment `testpypi` と `pypi` にTrusted Publisherを設定します。まずActionsの手動実行でTestPyPIへ公開してinstall smokeを行い、metadata、entry point、sdist内容を確認します。その後versionとCHANGELOGを確定し、maintainerの承認後に `v*` tagをpushしてPyPIへ公開します。テンプレート名のままtag/publishしないでください。

## Rename checklist

```text
lab_backend_template
lab-backend-template
ECHO::
echo (entry point name)
lab-backend (CLI command)
EchoBackend / MockEchoBackend
EchoResource / EchoWireError
GitHub project URLs
example instrument metadata
```
