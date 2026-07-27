# Changelog

## 0.2.0 - 2026-07-24

Add finite streaming acquisition for the BiTalino (r)evolution board, over both
Bluetooth Classic (RFCOMM) and BLE, without loosening the read-only guarantee the
environment sensors depend on. Both transports were exercised on hardware: 100
samples at 100 Hz from each unit, every frame passing CRC-4 with no sequence gap.

- Add an `ACQUIRE <samples> @<rate>` opcode that captures a bounded burst to an
  `.npz` artifact and returns only a JSON reference, mirroring the NI-DAQ
  backend's P1 pattern so the frozen `query() -> str` contract is untouched.
- Add a `bitalino_frame` module: BiTalino start/stop commands, per-channel frame
  decoding (10-bit A1–A4, 6-bit A5–A6), and CRC-4 verification, with an
  `encode_frame` inverse for tests and the mock.
- Add a `stream` profile access mode (transport, channels, rates, BLE
  characteristics) and the `bitalino_bt` / `bitalino_ble` profiles and instrument
  definitions, both `experimental` until verified on hardware.
- Add RFCOMM (pyserial, `[rfcomm]` extra) and BLE-notify transports; `ACQUIRE`
  only ever writes the board's own bounded start/stop bytes to the declared
  control path, so the sensor grammar still cannot express a write.
- Record dropped frames from the 4-bit sequence counter in the artifact rather
  than smoothing over them; add `artifact_dir` / `max_samples` / `port_map`
  configuration to the backend, discovery factory, and CLI.
- Replay 16 frames captured from a real board in the mock backend, and promote
  both BiTalino profiles from `experimental` to `tested` with the evidence
  recorded in their instrument definitions. Only 100 Hz on one unit per transport
  was exercised, so neither claims `verified`.
- Send BLE start/stop as acknowledged writes: the board's commands
  characteristic offers `write` but not write-without-response, and
  unacknowledged writes left it idle, yielding zero frames.

## 0.1.0 - 2026-07-21

First release. Both bundled profiles are verified against real hardware, and
the mock replays payloads captured from those devices, so the tests decode
bytes the devices actually sent rather than hand-written examples.

- Add the BLE sensor backend with strict `BLE::<profile>/<ADDRESS>` resource and
  read-only `READ`/`INFO` command parsers.
- Add declarative device profiles with verified `omron_2jcie` and
  `switchbot_meter` field maps, plus a codec for masked and split-nibble layouts.
- Add a mock backend that replays payloads captured from hardware on 2026-07-20.
- Add BEF conformance, read-only enforcement, profile decoding, routing, CLI,
  and packaging tests.
- Add instrument definitions in the ecosystem schema so `list_commands` and
  `execute_named_command` reach BLE devices the same way they reach VISA and
  Modbus devices, with tests binding each definition to its profile.
- Align `support_level` with the ecosystem vocabulary
  (`verified`/`tested`/`experimental`/`draft`).
- Add CI, Trusted Publishing, and documentation.
