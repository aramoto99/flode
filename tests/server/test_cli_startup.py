"""``pyflw-server`` 起動 UX (SPEC-0021 / ADR-0069) のテスト。

ポート自動フォールバック (事前 socket bind プローブ)、ブラウザ URL 正規化、
ブラウザ自動オープン (daemon スレッド + TCP ポーリング) を検証する。
``main()`` の統合テストは ``uvicorn.run`` と ``_launch_browser_thread`` を mock し、
実ブラウザ・実サーバを起動しない。
"""

from __future__ import annotations

import errno
import logging
import socket
import webbrowser
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from pyflw.exceptions import PyflwError
from pyflw.server import cli
from pyflw.server.cli import (
    _browser_url,
    _open_browser_when_ready,
    _probe_bind,
    find_free_port,
    main,
    normalize_browser_host,
)

# ``isolated_home`` fixture は tests/server/conftest.py で共有。


@pytest.fixture
def occupied_port() -> Iterator[int]:
    """実 socket で loopback の 1 ポートを占有し、そのポート番号を返す。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# find_free_port / _probe_bind (SPEC-0021 §4)
# ---------------------------------------------------------------------------


class TestFindFreePort:
    def test_returns_requested_port_when_free(self) -> None:
        # 空きポート番号を OS に割り当てさせてから close → その番号は高確率で空き
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
        probe.close()
        assert find_free_port("127.0.0.1", free_port, 50) == free_port

    def test_skips_busy_port(self, occupied_port: int) -> None:
        result = find_free_port("127.0.0.1", occupied_port, 50)
        assert result != occupied_port
        assert occupied_port < result <= occupied_port + 50

    def test_retries_zero_busy_raises(self, occupied_port: int) -> None:
        """port_retries=0 はフォールバック無効 = 使用中なら即 PyflwError (SPEC-0021 §4-2)。"""
        with pytest.raises(PyflwError, match=str(occupied_port)):
            find_free_port("127.0.0.1", occupied_port, 0)

    def test_exhausted_raises_with_range(self, mocker: MockerFixture) -> None:
        """全ポート使用中なら試行範囲入りのメッセージで PyflwError (SPEC-0021 §4-3)。"""
        mocker.patch.object(cli, "_probe_bind", return_value=False)
        with pytest.raises(PyflwError, match="9000-9003"):
            find_free_port("127.0.0.1", 9000, 3)

    def test_unresolvable_host_raises(self) -> None:
        with pytest.raises(PyflwError, match="resolve"):
            find_free_port("no-such-host.invalid", 8770, 0)

    def test_search_range_capped_at_max_tcp_port(self, mocker: MockerFixture) -> None:
        """port_retries 誤設定 (極端に大きい値) でも 65535 で探索を打ち切る。"""
        probe = mocker.patch.object(cli, "_probe_bind", return_value=False)
        with pytest.raises(PyflwError, match="65534-65535"):
            find_free_port("127.0.0.1", 65534, 100000)
        assert probe.call_count == 2  # 65534 と 65535 のみ

    def test_port0_above_max_raises(self) -> None:
        with pytest.raises(PyflwError, match="65535"):
            find_free_port("127.0.0.1", 65536, 0)

    def test_probe_bind_wraps_unexpected_oserror(self, mocker: MockerFixture) -> None:
        """EADDRINUSE 以外の OSError は「使用中」扱いにせず PyflwError で表面化する。"""
        fake_sock = mocker.MagicMock()
        fake_sock.bind.side_effect = OSError(errno.EPERM, "operation not permitted")
        mocker.patch("socket.socket", return_value=fake_sock)
        with pytest.raises(PyflwError, match="Failed to bind"):
            _probe_bind("127.0.0.1", 8770)
        fake_sock.close.assert_called_once()

    def test_probe_bind_reports_busy_on_eaddrinuse(self, mocker: MockerFixture) -> None:
        fake_sock = mocker.MagicMock()
        fake_sock.bind.side_effect = OSError(errno.EADDRINUSE, "address in use")
        mocker.patch("socket.socket", return_value=fake_sock)
        assert _probe_bind("127.0.0.1", 8770) is False


# ---------------------------------------------------------------------------
# normalize_browser_host / _browser_url (SPEC-0021 §4-D)
# ---------------------------------------------------------------------------


class TestNormalizeBrowserHost:
    @pytest.mark.parametrize(
        ("bind_host", "expected"),
        [
            ("127.0.0.1", "127.0.0.1"),
            ("localhost", "127.0.0.1"),
            ("0.0.0.0", "127.0.0.1"),
            ("::", "::1"),
            ("192.168.1.10", "192.168.1.10"),
        ],
    )
    def test_normalization_table(self, bind_host: str, expected: str) -> None:
        assert normalize_browser_host(bind_host) == expected


class TestBrowserUrl:
    def test_ipv4(self) -> None:
        assert _browser_url("127.0.0.1", 8770) == "http://127.0.0.1:8770"

    def test_ipv6_literal_gets_brackets(self) -> None:
        assert _browser_url("::1", 9000) == "http://[::1]:9000"


# ---------------------------------------------------------------------------
# _open_browser_when_ready (SPEC-0021 §1)
# ---------------------------------------------------------------------------


class TestOpenBrowserWhenReady:
    @pytest.fixture
    def fast_poll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ポーリングをテスト向けに高速化 (待ち時間ゼロ・3 回で打ち切り)。"""
        monkeypatch.setattr(cli, "_BROWSER_POLL_INTERVAL_S", 0.0)
        monkeypatch.setattr(cli, "_BROWSER_POLL_MAX_TRIES", 3)

    def test_opens_once_after_connection_established(self, mocker: MockerFixture) -> None:
        mocker.patch("socket.create_connection")  # 即成立
        mock_open = mocker.patch("webbrowser.open", return_value=True)
        _open_browser_when_ready("127.0.0.1", 8770, "http://127.0.0.1:8770")
        mock_open.assert_called_once_with("http://127.0.0.1:8770", new=2)

    def test_false_return_logs_warning_and_continues(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ヘッドレス環境想定: webbrowser.open が False → WARNING に URL を出して継続。"""
        mocker.patch("socket.create_connection")
        mocker.patch("webbrowser.open", return_value=False)
        with caplog.at_level(logging.WARNING, logger="pyflw.server.cli"):
            _open_browser_when_ready("127.0.0.1", 8770, "http://127.0.0.1:8770")
        assert any("http://127.0.0.1:8770" in r.message for r in caplog.records)

    def test_webbrowser_error_logged_not_raised(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        mocker.patch("socket.create_connection")
        mocker.patch("webbrowser.open", side_effect=webbrowser.Error("no browser"))
        with caplog.at_level(logging.WARNING, logger="pyflw.server.cli"):
            _open_browser_when_ready("127.0.0.1", 8770, "http://127.0.0.1:8770")
        assert any("http://127.0.0.1:8770" in r.message for r in caplog.records)

    def test_connection_never_ready_opens_best_effort(
        self, mocker: MockerFixture, fast_poll: None
    ) -> None:
        """上限試行到達でも best-effort で 1 回だけ開く (ADR-0069 実装メモ 3)。"""
        mocker.patch("socket.create_connection", side_effect=OSError("refused"))
        mock_open = mocker.patch("webbrowser.open", return_value=True)
        _open_browser_when_ready("127.0.0.1", 8770, "http://127.0.0.1:8770")
        mock_open.assert_called_once()


# ---------------------------------------------------------------------------
# main() 統合 (uvicorn.run / _launch_browser_thread を mock)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_uvicorn(mocker: MockerFixture) -> object:
    import uvicorn

    return mocker.patch.object(uvicorn, "run")


@pytest.fixture
def mock_browser_thread(mocker: MockerFixture) -> object:
    return mocker.patch.object(cli, "_launch_browser_thread")


class TestMainStartupIntegration:
    def test_port_fallback_passes_actual_port_to_uvicorn(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        mock_browser_thread,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        occupied_port: int,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with caplog.at_level(logging.WARNING, logger="pyflw.server.cli"):
            main(["--port", str(occupied_port)])
        _, kwargs = mock_uvicorn.call_args
        actual_port = kwargs["port"]
        assert actual_port != occupied_port
        # WARNING でポートずれを通知 (SPEC-0021 §4-4)
        assert any(str(occupied_port) in r.getMessage() for r in caplog.records)
        # ブラウザには実ポートを渡す (SPEC-0021 §4-D)
        mock_browser_thread.assert_called_once_with("127.0.0.1", actual_port)

    def test_browser_thread_launched_by_default(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        mock_browser_thread,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        main([])
        mock_browser_thread.assert_called_once()

    def test_no_browser_flag_skips_thread(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        mock_browser_thread,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        main(["--no-browser"])
        mock_browser_thread.assert_not_called()

    def test_no_browser_flag_wins_over_config_true(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        mock_browser_thread,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = isolated_home / ".pyflw" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("[server]\nopen_browser = true\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        main(["--no-browser"])
        mock_browser_thread.assert_not_called()

    def test_config_open_browser_false_skips_thread(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        mock_browser_thread,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = isolated_home / ".pyflw" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("[server]\nopen_browser = false\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        main([])
        mock_browser_thread.assert_not_called()

    def test_generate_config_skips_probe_and_browser(
        self,
        isolated_home: Path,
        mock_uvicorn,
        mock_browser_thread,
        mocker: MockerFixture,
    ) -> None:
        """early-exit 経路ではポート探索もブラウザ起動も通らない (SPEC-0021 §1-4)。"""
        mock_probe = mocker.patch.object(cli, "find_free_port")
        with pytest.raises(SystemExit):
            main(["--generate-config"])
        mock_probe.assert_not_called()
        mock_browser_thread.assert_not_called()
        mock_uvicorn.assert_not_called()
