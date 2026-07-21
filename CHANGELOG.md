# Changelog

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
