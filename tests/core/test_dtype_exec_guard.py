"""SPEC-0028 §3.8 / AC-7: static 型解決中の exec ガード。

「静的解決はユーザーコードを実行しない」の実行時バックストップ。
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flode import Simulator
from flode.blocks.pythonfunc import PythonFunction, exec_block_source
from flode.blocks.sources import Constant
from flode.core import dtypes
from flode.exceptions import BlockSpecError
from flode.server.app import create_app
from flode.server.settings import Settings

_VALID_CODE = textwrap.dedent(
    """
    @block
    def f(t: float, u: float) -> float:
        return u
    """
)


class TestExecGuard:
    def test_exec_is_rejected_while_flag_is_set(self) -> None:
        token = dtypes._RESOLVING_WITHOUT_USER_CODE.set(True)
        try:
            with pytest.raises(BlockSpecError, match="static dtype resolution"):
                exec_block_source(_VALID_CODE, block_id="pf")
        finally:
            dtypes._RESOLVING_WITHOUT_USER_CODE.reset(token)

    def test_exec_works_after_flag_is_reset(self) -> None:
        token = dtypes._RESOLVING_WITHOUT_USER_CODE.set(True)
        dtypes._RESOLVING_WITHOUT_USER_CODE.reset(token)
        cls, _ns = exec_block_source(_VALID_CODE, block_id="pf")
        assert cls is not None

    def test_static_resolution_sets_and_clears_flag(self) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        pf = sim.add(PythonFunction(code=_VALID_CODE, id="pf"))
        sim.connect(c, pf)
        assert dtypes.in_static_dtype_resolution() is False
        res = dtypes.resolve_dtypes(sim, mode="static")
        assert dtypes.in_static_dtype_resolution() is False  # 区間が漏れない
        assert any(d.code == "dtype.static_fallback" for d in res.diagnostics)

    def test_run_path_is_unaffected_by_guard(self) -> None:
        # full mode (run 経路) ではガードは立たず、正当な exec が通る
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=2.0, id="c"))
        pf = sim.add(PythonFunction(code=_VALID_CODE, id="pf"))
        from flode.blocks.sinks import Scope

        sc = sim.add(Scope(id="sc"))
        sim.connect(c, pf)
        sim.connect(pf, sc)
        sim.run()
        assert float(np.asarray(sc.values)[0, 0]) == 2.0

    def test_guard_propagates_through_threadpool_endpoint(self, tmp_path: Path) -> None:
        # REST 経由 (run_in_threadpool の worker thread) でも ContextVar が伝播し、
        # static 解決中に exec が呼ばれれば拒否される — が、そもそも呼ばれない
        # (marker 検証)。両方を 1 テストで固定
        marker = tmp_path / "executed.txt"
        code = textwrap.dedent(
            f"""
            open({str(marker)!r}, "w").write("executed")

            @block
            def f(t: float, u: float) -> float:
                return u
            """
        )
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        pf = sim.add(PythonFunction(code=code, id="pf"))
        sim.connect(c, pf)
        import json

        model_path = tmp_path / "m.flw.json"
        sim.save(model_path)
        model: dict[str, Any] = json.loads(model_path.read_text(encoding="utf-8"))
        if marker.exists():
            marker.unlink()  # 防御的 cleanup (v0.54.1 以降 save は exec しない)

        settings = Settings(workspace_root=tmp_path)
        app = create_app(settings=settings)
        with TestClient(app) as client:
            resp = client.post("/api/v1/models/resolve-dtypes", json={"model": model})
        assert resp.status_code == 200
        assert not marker.exists()
        codes = [d["code"] for d in resp.json()["diagnostics"]]
        assert "dtype.static_fallback" in codes
        assert "dtype.internal_error" not in codes  # ガード誤発火なし
