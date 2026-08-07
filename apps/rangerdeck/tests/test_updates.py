"""Update channel: compare, fetch injection, GUI chip and Install path."""
from __future__ import annotations

import json
from pathlib import Path

import pygame
import pytest

from core.engine import DeckFleet
from core.registry import AppSpec
from core.updates import (STATUS_AVAILABLE, STATUS_CURRENT, STATUS_DISABLED,
                          STATUS_ERROR, ChannelInfo, UpdateSettings,
                          UpdateState, check_for_update, commits_match,
                          read_local_channel, start_check, write_local_channel)
from gui.app import App

SPECS = (
    AppSpec("midiranger", "MidiRanger", "matrix", ("py", "m")),
    AppSpec("genranger", "GenRanger", "generative", ("py", "m")),
)


class IdleClient:
    def send(self, command):
        return True

    def wait_event(self, timeout=None):
        return None

    def drain(self):
        return []

    def close(self):
        pass


class IdleProcess:
    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass


def test_commits_match_accepts_short_and_full():
    assert commits_match("abcdef1", "abcdef1234567890")
    assert commits_match("ABCDEF1234567890", "abcdef1")
    assert not commits_match("abcdef1", "abcdef2")
    assert not commits_match("", "abcdef1")


def test_read_local_prefers_installed_channel(tmp_path):
    settings = UpdateSettings(state_dir=tmp_path, opt_root=tmp_path / "opt")
    write_local_channel(settings, ChannelInfo(version="0.2.0",
                                              commit="abc1234deadbeef"))
    info = read_local_channel(settings)
    assert info.version == "0.2.0"
    assert info.commit.startswith("abc1234")


def test_read_local_falls_back_to_bake_marker(tmp_path):
    opt = tmp_path / "opt" / "rangerdeck"
    opt.mkdir(parents=True)
    (opt / ".patchbox-source-commit").write_text("cafebabedeadbeef\n")
    settings = UpdateSettings(state_dir=tmp_path / "state", opt_root=tmp_path / "opt")
    info = read_local_channel(settings)
    assert info.commit.startswith("cafebab")


def test_check_reports_available_when_remote_moves(tmp_path):
    settings = UpdateSettings(state_dir=tmp_path, enabled=True)
    write_local_channel(settings, ChannelInfo(commit="aaaaaaa1111111"))

    def fetcher(_settings):
        return ChannelInfo(version="0.3.0", commit="bbbbbbb2222222",
                           notes="power tile")

    status, local, remote, detail = check_for_update(settings, fetcher)
    assert status == STATUS_AVAILABLE
    assert remote.version == "0.3.0"
    assert "power" in detail or "0.3" in detail
    assert local.commit.startswith("aaaaaaa")


def test_check_reports_current_when_tips_match(tmp_path):
    settings = UpdateSettings(state_dir=tmp_path)
    write_local_channel(settings, ChannelInfo(commit="abcdef1234567890"))

    def fetcher(_settings):
        return ChannelInfo(commit="abcdef1")

    status, _local, _remote, detail = check_for_update(settings, fetcher)
    assert status == STATUS_CURRENT
    assert "up to date" in detail


def test_check_disabled(tmp_path):
    settings = UpdateSettings(state_dir=tmp_path, enabled=False)
    status, *_ = check_for_update(settings, lambda s: ChannelInfo(commit="x"))
    assert status == STATUS_DISABLED


def test_check_error_on_fetcher_raise(tmp_path):
    settings = UpdateSettings(state_dir=tmp_path)

    def boom(_settings):
        raise RuntimeError("offline")

    status, _l, _r, detail = check_for_update(settings, boom)
    assert status == STATUS_ERROR
    assert "offline" in detail


def test_header_chip_and_install_path(tmp_path):
    fleet = DeckFleet(SPECS, tmp_path,
                      spawn=lambda command: IdleProcess(),
                      connect=lambda name, timeout: IdleClient())
    state = UpdateState()
    state.set(STATUS_AVAILABLE,
              local=ChannelInfo(commit="aaa1111"),
              remote=ChannelInfo(version="0.9.0", commit="bbb2222",
                                 notes="fixes"),
              detail="0.9.0 — fixes")
    applied = []

    def runner():
        applied.append(True)
        return True, "UPDATED bbb2222"

    app = App(fleet, size=(1280, 400), update_state=state,
              update_apply=runner, start_update_check=False)
    try:
        app._draw()
        chip = app.chrome.rect_for("update:open")
        assert chip is not None
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=chip.center))
        app._events()
        assert app._update_menu is True
        app._draw()
        install = app.chrome.rect_for("update:install")
        assert install is not None
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=install.center))
        app._events()
        assert applied == [True]
        assert "UPDATED" in app._message
    finally:
        pygame.display.quit()


def test_start_check_thread_reaches_available(tmp_path):
    settings = UpdateSettings(state_dir=tmp_path, check_on_launch=True,
                              enabled=True)
    write_local_channel(settings, ChannelInfo(commit="oldold1"))
    state = UpdateState()
    done = []

    def fetcher(_s):
        return ChannelInfo(commit="newnew2", version="1.0.0")

    start_check(settings, state, fetcher=fetcher,
                on_done=lambda: done.append(1))
    # Wait briefly for the daemon thread.
    import time
    for _ in range(50):
        if done:
            break
        time.sleep(0.02)
    status, _l, remote, _d = state.snapshot()
    assert status == STATUS_AVAILABLE
    assert remote.version == "1.0.0"
