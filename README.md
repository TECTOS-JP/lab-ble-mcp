# lab-ble-mcp

[lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp) 用の BLE 環境センサ backend です。温湿度・気圧・CO2 などを実験記録の一部として取得します。

## 対応機種

| profile | 機器 | 取得できる測定量 | 経路 |
| --- | --- | --- | --- |
| `omron_2jcie` | OMRON 2JCIE-BU01 | 温度・湿度・照度・気圧・騒音・eTVOC・eCO2 | advertisement / GATT |
| `switchbot_meter` | SwitchBot Meter | 温度・湿度・電池残量 | advertisement のみ |

どちらの profile も実機で検証済みです（2026-07-20）。同梱の mock backend は、そのとき実機から採取したペイロードをそのまま再生します。テストは手書きの例ではなく、**装置が実際に送出したバイト列**を復号して検証しています。

## 使い方

```powershell
python -m pip install -e ".[dev]"
pytest -q
lab-ble profiles
lab-ble serve --resource "BLE::omron_2jcie/D0:ED:3E:53:EE:22" --dry-run
```

- resource: `BLE::<profile>/<ADDRESS>`
  - profile は小文字の slug、address は大文字コロン区切り。正規形は1つだけで、小文字アドレスは黙って変換せず拒否します。
  - profile を resource 名に含めるのは、BLE のペイロードが自己記述的でないためです。復号器はバイトを解釈する前に確定している必要があり、設定ミスで別ベンダのフィールド地図を当ててしまう事故を防ぎます。
- query: `READ <測定量>` / `INFO <項目>`
- write: **ありません**（後述）

```powershell
lab-ble serve --resource "BLE::switchbot_meter/D6:DF:02:E9:08:48"
```

### Python library

```python
from lab_ble_mcp import BleBackend

backend = BleBackend(resources=["BLE::omron_2jcie/D0:ED:3E:53:EE:22"])
value = await backend.query("BLE::omron_2jcie/D0:ED:3E:53:EE:22", "READ temperature")
```

### lab-executor backend discovery

インストール時に entry point `lab_executor.backends: ble` が登録されます。`lab-executor serve --backends ble` または `_system.yaml` の `backends:` から選択できます。

## 安全設計

**この backend は書き込みを一切行いません。** コマンド文法に write の opcode が存在しないため、実行時の許可リストに頼らず、文法上writeを表現できません。

これは理屈ではなく実機の観察に基づく判断です。OMRON 2JCIE-BU01 は閾値設定用の書き込み可能な characteristic に加えて、Nordic buttonless DFU characteristic (`8ec90003-f315-4f60-9fb8-838830daea50`) を公開しています。ここへ誤って書き込むと装置が使用不能になり得ます。測定用 backend がそこへ到達する理由はありません。

その他の原則:

- 未知の resource、未知の opcode、profile が公開していない測定量、長さの足りないペイロードは、推測せず fail-closed で拒否します。
- 読み取りは profile が両経路を持つ場合 advertisement を優先します。ブロードキャストは接続枠を消費しないため、ポーリングがスマートフォンアプリや他ホストを締め出しません。書き込み可能な characteristic へ接続すること自体を避けられます。
- `support_level: verified` は、実機から採取したペイロードがその profile で復号できる場合にのみ宣言できます（テストで強制）。

## 対応機種を増やす

多くの機器は profile の YAML を `src/lab_ble_mcp/profiles/` に1枚追加するだけで対応できます。Python の変更が必要になるのは、フィールドが固定幅リトルエンディアンで表現できない場合だけです（SwitchBot の温度は2バイトにまたがるマスク済みニブルなので、`codec.CUSTOM_DECODERS` に専用の復号器を持ちます）。

## 制約

- **連続ストリーミングは対象外です。** 現行の BEF 契約は `query() -> str` に凍結されており、波形や生体信号のような連続データが backend から出ていく経路がありません。BITalino 等のストリーミング機器はこの制約の対象です。
- **advertisement の送出間隔は機種差が大きく、待ち時間を要します。** `timeout_ms` は黙って延長せず、その操作の期限としてそのまま使います。実測では 2JCIE-BU01 は数秒間隔で安定して取得できましたが、SwitchBot Meter は不規則で、25000 ms でも取り逃すことがありました。定期取得では `cache_ttl_ms`（既定 10000 ms）が1回の受信を複数の測定量へ行き渡らせるため、測定量ごとに待ち直すことはありません。
- `list_resources()` は設定された resource だけを返します。BLE のスキャンは profile を持たない近隣のビーコンまで列挙してしまうためです。

## 開発と公開

CI は Python 3.11、Ruff、BEF 適合、latest release 統合、lab-executor main 互換 smoke、build を検証します。タグは PyPI、手動 workflow は既定で TestPyPI へ Trusted Publishing で公開します。

## ライセンス

MIT
