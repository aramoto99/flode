"""ADR-0039: ``flode/libraries/std.flwlib.json`` を ``libraries.v2`` 形式で再生成する一度きりのスクリプト。

v1 (= schema 0.7 形式の subsystem.params) から v2 (= schema 0.8 形式、
``n_inputs`` / ``n_outputs`` / ``port_shapes_*`` フィールド削除) への変換を行う。

実行:

    python scripts/regenerate_std_library.py

副作用: ``flode/libraries/std.flwlib.json`` を上書きする。

実装方針: 既存 v1 JSON を読み、libraries.v2 migration (``_migrate_libraries_v1_to_v2``)
で派生フィールド除去 → そのまま書き戻す。これにより entry id / display_name /
mask_params / 内部 blocks / connections / layout はすべて bit-by-bit 維持される。
"""

from __future__ import annotations

import json
from pathlib import Path

from flode.libraries._loader import _migrate_libraries_v1_to_v2


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "flode" / "libraries" / "std.flwlib.json"
    if not target.exists():
        raise SystemExit(f"target file not found: {target}")
    with target.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema_version") == "libraries.v2":
        print(f"Already libraries.v2; nothing to do: {target}")
        return
    if data.get("schema_version") != "libraries.v1":
        raise SystemExit(
            f"Unexpected schema_version {data.get('schema_version')!r}; "
            f"expected libraries.v1 or libraries.v2"
        )
    migrated = _migrate_libraries_v1_to_v2(data)
    with target.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(migrated, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Regenerated to libraries.v2: {target}")


if __name__ == "__main__":
    main()
