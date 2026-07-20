# 対応機種を追加する

多くの機器は `src/lab_ble_mcp/profiles/<name>.yaml` を1枚追加するだけで対応できます。Python の変更が必要なのは、フィールドが固定幅リトルエンディアン整数として表現できない場合だけです。

## 1. 実機のペイロードを採取する

推測で profile を書かないでください。まず装置が実際に何を送出しているかを見ます。

```python
import asyncio
from bleak import BleakScanner

async def main():
    found = {}
    scanner = BleakScanner(detection_callback=lambda d, ad: found.update({d.address: (d, ad)}))
    await scanner.start(); await asyncio.sleep(15); await scanner.stop()
    for address, (device, ad) in found.items():
        print(address, repr(ad.local_name), ad.rssi)
        for company, data in ad.manufacturer_data.items():
            print(f"  mfr[0x{company:04X}]: {data.hex()}")
        for uuid, data in ad.service_data.items():
            print(f"  svc[{uuid}]: {data.hex()}")

asyncio.run(main())
```

**同じ機器を時間をおいて2回以上採取してください。** 1回の採取ではフィールドの位置を取り違えても気づけません。連番が進むか、気圧のように安定した量が動かず、騒音のように動的な量が動くか——物理的に妥当な振る舞いをするかどうかが、復号仕様が正しいことの実質的な証拠になります。ペイロードが一切変化しない場合、その機器はアドバタイズでは実測値を更新していない可能性があります。

GATT 経路も使う場合は、`BleakClient` で service と characteristic を列挙し、読み取り可能なものの値を確認します。同じ測定量が両経路から取れるなら、**両者が一致することが最も強い検証**になります。

## 2. profile を書く

```yaml
profile: acme_th1          # ファイル名と一致させる（不一致は読み込み時に拒否）

metadata:
  manufacturer: "ACME"
  model: "TH-1"
  category: "environment_sensor"
  support_level: "experimental"
  definition_version: "0.1.0"
  manual_ref: "ACME TH-1 BLE spec rev.2"
  description: >-
    温湿度センサ。

access:
  advertisement:
    manufacturer_id: 0x1234        # または service_uuid: のどちらか一方だけ
    fields:
      temperature: {offset: 2, type: i16le, scale: 0.01, unit: "degC"}
      humidity:    {offset: 4, type: u8, mask: 0x7F, unit: "percent_rh"}
  gatt:
    characteristic: "0000abcd-0000-1000-8000-00805f9b34fb"
    fields:
      temperature: {offset: 1, type: i16le, scale: 0.01, unit: "degC"}
```

- `type`: `u8` `i8` `u16le` `i16le` `u32le` `i32le`
- `mask`: 論理積を取ってから `scale` を掛けます
- `unit`: 必須。単位のないフィールドは受け付けません
- `access` は `advertisement` と `gatt` の少なくとも一方が必要です。両方ある場合、読み取りは advertisement を優先します

### 固定幅で表現できない場合

SwitchBot の温度のように、複数バイトのマスク済みニブルにまたがる配置は宣言では書けません。`codec.py` の `CUSTOM_DECODERS` に関数を追加し、profile 側では次のように参照します。

```yaml
temperature: {decoder: "switchbot_temp_c", unit: "degC"}
```

`decoder` を使うフィールドに `offset` / `type` / `mask` / `scale` を併記することはできません（読み込み時に拒否されます）。

## 3. 採取したペイロードをテストに組み込む

`mock_backend.CAPTURED_PAYLOADS` に実機のバイト列を追加し、`tests/test_profiles.py` に期待する物理量を書きます。これによりテストが手書きの例ではなく実機の出力に対して回ります。

## 4. support_level を正しく宣言する

- `experimental`: 実機未検証。仕様書だけから起こした場合
- `mock_verified`: 採取済みペイロードでの復号のみ確認
- `verified`: 対象実機で確認済み

`verified` を宣言する profile は `CAPTURED_PAYLOADS` に実機ペイロードを持つことがテストで強制されます。実機を持たないまま `verified` にすることはできません。

## 5. 書き込みは追加しない

コマンド文法に write の opcode はありません。閾値設定や DFU の characteristic へ到達する経路を作らないでください。測定用 backend がそこへ触れる理由はなく、誤書き込みは装置を使用不能にし得ます。
