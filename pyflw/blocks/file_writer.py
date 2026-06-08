"""SPEC-0016 / ADR-0066 (v0.39.0+): FileWriter sink ブロック (データエクスポート)。

Scope と同じ ``record`` / ``times`` / ``values`` / ``labels`` インタフェースを
持ち、加えて ``save_npz`` / ``save_csv`` でファイル書き出し API を提供する。

v0.39.1 amendment: ``path`` / ``format`` パラメータを追加し、``Simulator.run()``
終了時に **自動 save** する経路を実装 (GUI で配置するだけで出力が出る)。
``path=""`` (空) のときは旧挙動 (= 明示 ``save_npz`` / ``save_csv`` のみ)。
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import FileWriteError, PathTraversalError, PyflwError

_logger = logging.getLogger(__name__)


class FileWriter(Block):
    """シミュレーション結果をファイル (npz / csv) に出力する sink ブロック。

    Args:
        n_inputs: 入力ポート数 (>= 1)。
        labels: 各信号の列名 (省略時は ``in0``, ``in1`` ...)。長さは
            ``n_inputs`` と一致必須。
        path: 自動 save 先パス (省略 / 空文字 で自動 save 無効)。絶対パス
            または相対パス。
            **server 経由実行時** は workspace root 基準で resolve され
            path traversal が検証される (ADR-0041)。**Python 直接実行時**
            は CWD 基準で書く。
        format: 出力フォーマット (``"auto"`` / ``"csv"`` / ``"npz"``)。
            ``"auto"`` は ``path`` の拡張子から推測 (`.csv` → ``"csv"``、
            `.npz` → ``"npz"``)。``path`` が空のとき format は無視される。

    Raises:
        BlockSpecError: ``n_inputs < 1`` / ``labels`` 長不一致 / ``format``
            enum 値外 / ``path`` 非空で format=``"auto"`` かつ拡張子不明。
        FileWriteError: ``Simulator.run()`` の自動 save 経路でディスク書き
            込みに失敗 (OSError / PathTraversalError ラップ)。

    Example:
        >>> # GUI 用途: path を指定すれば run() 終了時に自動 save
        >>> sim.add(FileWriter(n_inputs=1, path="output.csv", id="fw"))
        >>> sim.run()
        >>> # → "output.csv" が自動生成される
        >>>
        >>> # Python 用途 (path 省略): 明示的に save を呼ぶ (旧挙動互換)
        >>> sim.add(FileWriter(n_inputs=1, id="fw"))
        >>> sim.run()
        >>> sim.get_block("fw").save_csv("output.csv")
    """

    _ALLOWED_FORMATS: tuple[str, ...] = ("auto", "csv", "npz")
    _param_enums = {"format": _ALLOWED_FORMATS}

    def __init__(
        self,
        n_inputs: int = 1,
        labels: list[str] | None = None,
        path: str = "",
        format: str = "auto",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        # ローカル import で circular import を避ける
        from ..exceptions import BlockSpecError

        if n_inputs < 1:
            raise BlockSpecError(f"FileWriter: n_inputs must be >= 1, got {n_inputs}")
        if labels is not None and len(labels) != n_inputs:
            raise BlockSpecError(
                f"FileWriter: len(labels)={len(labels)} must equal n_inputs={n_inputs}"
            )
        if format not in self._ALLOWED_FORMATS:
            raise BlockSpecError(
                f"FileWriter: format must be one of {self._ALLOWED_FORMATS}, got {format!r}"
            )

        # path 非空かつ format="auto" のとき、拡張子から format を決定
        # (拡張子不明 = .csv / .npz 以外なら BlockSpecError)
        if path:
            resolved_format = self._resolve_format(path, format)
            if resolved_format is None:
                raise BlockSpecError(
                    f"FileWriter: cannot infer format from path={path!r} "
                    f"(extension must be .csv or .npz, or set format explicitly)"
                )
        else:
            resolved_format = format  # path 空時は format 検証だけ済ませる

        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=0)
        self.labels: list[str] = labels or [f"in{i}" for i in range(n_inputs)]
        self.path: str = path
        self.format: str = format
        self._resolved_format: str = resolved_format
        self.times: list[float] = []
        self._values: list[npt.NDArray[Any]] = []
        self._params: dict[str, Any] = {
            "n_inputs": int(n_inputs),
            "labels": self.labels,
            "path": path,
            "format": format,
        }

    @staticmethod
    def _resolve_format(path: str, format: str) -> str | None:
        """``format="auto"`` のとき拡張子から format を決定する。

        Returns:
            ``"csv"`` / ``"npz"`` / 元の format 値 (auto でない場合)。
            判定不能なら ``None``。
        """
        if format != "auto":
            return format
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            return "csv"
        if suffix == ".npz":
            return "npz"
        return None

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def reset(self) -> None:
        """``Simulator.run()`` 開始時の lifecycle hook。バッファをクリア。"""
        self.times = []
        self._values = []

    def record(self, t: float, u: npt.NDArray[Any]) -> None:
        """Simulator が各 step で呼ぶ (Scope と同型インタフェース)。"""
        self.times.append(float(t))
        self._values.append(np.asarray(u, dtype=float).copy())

    @property
    def values(self) -> npt.NDArray[Any]:
        if not self._values:
            return np.empty((0, self.n_inputs))
        return np.array(self._values)

    def _finalize(self, workspace_root: Path | None = None) -> None:
        """``Simulator.run()`` 終了時に呼ばれる lifecycle hook (v0.39.1)。

        ``path`` が非空のとき、format に応じて自動 save する。

        Args:
            workspace_root: server 経由実行時の workspace root (ADR-0041 path
                traversal 防御)。``None`` なら絶対パス / CWD 相対パスを
                そのまま使う (Python 直接実行時)。

        Raises:
            FileWriteError: ディスク書き込み失敗 (OSError / PathTraversalError
                をラップ、block_id 付き)。
        """
        if not self.path:
            return  # 自動 save 無効、Python API 経由のみ

        try:
            resolved_path = self._resolve_path(self.path, workspace_root)
        except PathTraversalError as exc:
            raise FileWriteError(
                f"FileWriter[{self.name}]: path {self.path!r} escapes workspace root",
                block_id=self.id,
            ) from exc

        _logger.info(
            "FileWriter[%s]: auto-saving %s rows to %s (format=%s)",
            self.id,
            len(self.times),
            resolved_path,
            self._resolved_format,
        )
        try:
            if self._resolved_format == "csv":
                self.save_csv(resolved_path)
            elif self._resolved_format == "npz":
                self.save_npz(resolved_path)
            else:
                # __init__ で reject されるはずだが、防御的に
                raise FileWriteError(
                    f"FileWriter[{self.name}]: unknown format {self._resolved_format!r}",
                    block_id=self.id,
                )
        except OSError as exc:
            raise FileWriteError(
                f"FileWriter[{self.name}]: failed to write {resolved_path!r}: {exc}",
                block_id=self.id,
            ) from exc

    @staticmethod
    def _resolve_path(path: str, workspace_root: Path | None) -> Path:
        """``path`` を絶対パスに解決する。

        - ``workspace_root`` が None: 絶対パスならそのまま、相対なら CWD 基準
        - ``workspace_root`` 指定時: 必ず workspace 配下に閉じる (ADR-0041)。
          絶対パス指定でも workspace root 配下に強制 (escape は
          PathTraversalError)
        """
        p = Path(path)
        if workspace_root is None:
            return p if p.is_absolute() else (Path.cwd() / p).resolve()

        # ADR-0041: workspace 配下に閉じる
        workspace_root = workspace_root.resolve()
        if p.is_absolute():
            candidate = p.resolve()
        else:
            candidate = (workspace_root / p).resolve()
        # candidate が workspace_root 配下かを is_relative_to で検証
        try:
            candidate.relative_to(workspace_root)
        except ValueError as exc:
            raise PathTraversalError(
                f"path {path!r} escapes workspace root {workspace_root}"
            ) from exc
        return candidate

    def save_npz(self, path: str | Path) -> None:
        """numpy ``.npz`` 形式で保存。``time`` と labels-named array を含む。

        Note:
            v0.39.1 で ``_finalize`` から呼ばれる経路を追加したが、本メソッド
            自身は Python API として **引き続きユーザーが直接呼べる** (= 後方互換)。
        """
        path = Path(path)
        v = self.values
        arrays: dict[str, npt.NDArray[Any]] = {"time": np.array(self.times)}
        for i, lbl in enumerate(self.labels):
            arrays[lbl] = v[:, i] if v.size else np.empty(0)
        np.savez(path, **arrays)  # type: ignore[arg-type]

    def save_csv(self, path: str | Path) -> None:
        """CSV 形式で保存。1 列目=``time``、残り=labels 列。

        Note:
            v0.39.1 で ``_finalize`` から呼ばれる経路を追加したが、本メソッド
            自身は Python API として **引き続きユーザーが直接呼べる** (= 後方互換)。
        """
        path = Path(path)
        v = self.values
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time", *self.labels])
            for i, t in enumerate(self.times):
                row = [t, *v[i].tolist()] if v.size else [t]
                writer.writerow(row)


# 未使用 import 警告抑制 (PyflwError は将来の subclass 用に re-export)
_ = PyflwError
