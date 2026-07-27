# lab-ble-mcp

[lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp) 用の BLE backend です。温湿度・気圧・CO2 などの環境センサを実験記録の一部として取得するほか、BiTalino 生体信号ボードの有限ストリーミング取得(`ACQUIRE`)にも対応します。

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

### Python library として使う

```python
from lab_ble_mcp import BleBackend

backend = BleBackend(resources=["BLE::omron_2jcie/D0:ED:3E:53:EE:22"])
value = await backend.query("BLE::omron_2jcie/D0:ED:3E:53:EE:22", "READ temperature")
```

### lab-executor による backend discovery

インストール時に entry point `lab_executor.backends: ble` が登録されます。`lab-executor serve --backends ble` または `_system.yaml` の `backends:` から選択できます。

## ストリーミング取得(BiTalino)

環境センサが「1回の値」を返すのに対し、[BiTalino (r)evolution](https://www.pluxbiosignals.com/) は開始を指示してからフレームを連続送出する生体信号ボードです。read-only 設計には載らないため、専用の `ACQUIRE` 経路で扱います。

| profile | 機器 | 経路 | チャネル |
| --- | --- | --- | --- |
| `bitalino_bt` | BiTalino (r)evolution (BT) | RFCOMM シリアル | A1–A6(A1–A4 は 10bit、A5–A6 は 6bit、生 ADC 値) |
| `bitalino_ble` | BiTalino (r)evolution (BLE) | BLE notify | 同上 |

**どちらも実機で検証済みです(2026-07-24)。** 両機とも 100 Hz で 100 サンプルを取得し、全フレームが CRC4 を通過、シーケンス番号に欠落なし(`dropped_frames` = 0)、未接続の A1 は 427 counts 付近の実 ADC ノイズを示しました。同梱 mock は、このとき BT 機から採取した実フレームをそのまま再生します。`support_level` が `verified` でなく `tested` なのは、検証したのが 100 Hz・各1台のみで、1000 Hz とセンサ接続時のチャネルが未確認のためです。

```powershell
# 100 Hz で 1 秒(100 サンプル)を取得し、アーティファクト参照を得る
lab-ble serve --resource "BLE::bitalino_bt/AA:BB:CC:DD:EE:FF" `
  --artifact-dir ./artifacts --max-samples 60000 `
  --port-map "AA:BB:CC:DD:EE:FF=COM7"
```

- query: `ACQUIRE <サンプル数> @<レート>`(例 `ACQUIRE 100 @100`)。チャネルは profile が固定し、対応レートは 1 / 10 / 100 / 1000 Hz。
- 取得結果は `.npz`(生 ADC 値 `analog` 形状 `[サンプル数, チャネル数]`、`digital`、`sequence`、`meta`)へ保存し、`query()` は `{"artifact":"v1","name":…,"sha256":…,"shape":…,"dropped_frames":…}` を返します。NI-DAQ backend と同じ P1 方式です。
- 4bit のシーケンス番号で取りこぼしを数え、`dropped_frames` として記録します(黙って補間しません)。
- **BT** は RFCOMM ポートが必要です(Windows は SPP の COM ポート)。`--port-map "<ADDR>=<PORT>"` で resource アドレス(MAC)に紐付けます。pyserial が要ります(`pip install lab-ble-mcp[rfcomm]`)。
  - **ポートは2つ現れることがあります。** 機器の MAC がハードウェア ID に含まれている方(送信用)を指定してください。もう一方は着信用で、開くとブロックします。`python -m serial.tools.list_ports -v` の `hwid` で判別できます。
- **BLE** は profile 内で宣言した commands / frames characteristic を使います。フレーム形式は BT と同一であることを実機で確認済みです。commands characteristic は応答ありの `write` のみを備え `write-without-response` を持たないため、開始/停止は応答あり書き込みで送ります(応答なしでは開始コマンドが届かず 0 フレームになります)。

## 安全設計

**センサ profile(環境センサ)は書き込みを一切行いません。** コマンド文法(`READ` / `INFO`)に write の opcode が存在しないため、実行時の許可リストに頼らず、文法上 write を表現できません。

これは理屈ではなく実機の観察に基づく判断です。OMRON 2JCIE-BU01 は閾値設定用の書き込み可能な characteristic に加えて、Nordic buttonless DFU characteristic (`8ec90003-f315-4f60-9fb8-838830daea50`) を公開しています。ここへ誤って書き込むと装置が使用不能になり得ます。測定用 backend がそこへ到達する理由はありません。

**ストリーミング profile(BiTalino)だけは例外的に、`ACQUIRE` の内部で開始/停止の制御バイトを書き込みます。** ただし到達先は profile が宣言した制御パス(BLE は commands characteristic、RFCOMM はそのポート)に限られ、呼び出し側が characteristic や値を指定できる汎用 write は依然として存在しません。BiTalino は測定専用ボードで、OMRON の DFU characteristic のような「装置を使用不能にする書き込み先」を露出していないため、この限定的な書き込みは安全です。

その他の原則:

- 未知の resource、未知の opcode、profile が公開していない測定量、長さの足りないペイロードは、推測せず fail-closed で拒否します。
- 読み取りは profile が両経路を持つ場合 advertisement を優先します。ブロードキャストは接続枠を消費しないため、ポーリングがスマートフォンアプリや他ホストを締め出しません。書き込み可能な characteristic へ接続すること自体を避けられます。
- `support_level: verified` は、実機から採取したペイロードがその profile で復号できる場合にのみ宣言できます（テストで強制）。

## 機器ごとの2つの定義ファイル

機器1台につき、役割の異なる YAML を2枚持ちます（**ファイル名は同じ**）。

| ファイル | 答える問い | 位置づけ |
| --- | --- | --- |
| `profiles/<name>.yaml` | バイト列をどう物理量へ復号するか | BLE 固有。SCPI は文字列を返すので VISA には無い層 |
| `builtin_instruments/<name>.yaml` | 名前付きコマンドは何があるか、単位・説明 | lab-executor エコシステム共通。`list_commands` / `execute_named_command` の情報源 |

機器定義の `scpi` にはこの backend のワイヤ言語（`READ temperature` 等）を書きます。SCPI ではありませんが、エコシステムの `InstrumentDefinition` 形式に揃えることで VISA・Modbus 機器と同じ手順で扱えます。

2つの文書は手書きなので乖離し得ます。そのためテストで、測定量とコマンドが過不足なく一致すること、全 `scpi` がワイヤ文法で解析できること、`state_query` の単位が一致すること、`support_level` が一致することを強制しています。

## 対応機種を増やす

上記2枚の YAML を追加します。Python の変更が必要になるのは、フィールドが固定幅リトルエンディアンで表現できない場合だけです（SwitchBot の温度は2バイトにまたがるマスク済みニブルなので、`codec.CUSTOM_DECODERS` に専用の復号器を持ちます）。詳細は [ADDING_A_PROFILE.md](docs/ADDING_A_PROFILE.md) を参照してください。

## 制約

- **連続ストリーミングは `ACQUIRE`(有限バルク取得)として扱います。** `query() -> str` の凍結契約を壊さないよう、生データを inline で返さず、指定サンプル数のバーストを `.npz` アーティファクトへ保存して参照 JSON だけを返します。したがって「終端のない無限ストリーム」や backend から連続データを push し続ける経路は依然としてありません。
- **advertisement の送出間隔は機種差が大きく、待ち時間を要します。** `timeout_ms` は黙って延長せず、その操作の期限としてそのまま使います。実測では 2JCIE-BU01 は数秒間隔で安定して取得できましたが、SwitchBot Meter は不規則で、25000 ms でも取り逃すことがありました。定期取得では `cache_ttl_ms`（既定 10000 ms）が1回の受信を複数の測定量へ行き渡らせるため、測定量ごとに待ち直すことはありません。
- `list_resources()` は設定された resource だけを返します。BLE のスキャンは profile を持たない近隣のビーコンまで列挙してしまうためです。

## 開発と公開

CI は Python 3.11、Ruff、BEF 適合、latest release 統合、lab-executor main 互換 smoke、build を検証します。タグは PyPI、手動 workflow は既定で TestPyPI へ Trusted Publishing で公開します。

## ライセンス

MIT
