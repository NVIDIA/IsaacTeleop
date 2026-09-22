# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The asset cache moved in 1.6, and both ways of noticing must still work."""

import logging
import re
import subprocess

import pytest

from isaaccapture.viz.robot import assets


def test_cache_dir_is_under_the_new_name(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(assets.CACHE_ENV_VAR, raising=False)
    dest = assets._cache_dir(assets.CACHE_ENV_VAR, "so101-assets")
    assert dest == tmp_path / "isaaccapture" / "so101-assets"


@pytest.mark.parametrize("env_var", [assets.CACHE_ENV_VAR, assets.REBOT_CACHE_ENV_VAR])
def test_a_legacy_override_warns_and_is_not_read(
    tmp_path, monkeypatch, caplog, env_var
):
    """The silent path: the fetch succeeds and the operator runs upstream geometry.

    Nothing else fires here -- no error, no missing file -- so the warning is the
    only signal that a curated site cache stopped being used.
    """
    legacy = env_var.replace("ISAACCAPTURE_", "ISAACTELEOP_", 1)
    curated = tmp_path / "site-assets"
    curated.mkdir()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv(legacy, str(curated))
    monkeypatch.delenv(env_var, raising=False)

    with caplog.at_level(logging.WARNING, logger=assets.LOG.name):
        dest = assets._cache_dir(env_var, "some-assets")

    assert dest != curated
    assert legacy in caplog.text
    assert env_var in caplog.text


def test_the_new_override_is_read_without_warning(tmp_path, monkeypatch, caplog):
    curated = tmp_path / "site-assets"
    monkeypatch.setenv(assets.CACHE_ENV_VAR, str(curated))
    monkeypatch.setenv(
        assets.CACHE_ENV_VAR.replace("ISAACCAPTURE_", "ISAACTELEOP_", 1), str(tmp_path)
    )

    with caplog.at_level(logging.WARNING, logger=assets.LOG.name):
        dest = assets._cache_dir(assets.CACHE_ENV_VAR, "so101-assets")

    assert dest == curated
    assert caplog.text == ""


def _refuse_to_fetch(monkeypatch):
    def _refuse(_url):
        raise OSError("Temporary failure in name resolution")

    monkeypatch.setattr(assets, "_fetch", _refuse)


def _populated_1_5_cache(tmp_path):
    """What 1.5 left behind: meshes plus the completeness marker that gates the
    download. Both survive the copy, which is the whole basis for advising one."""
    legacy = tmp_path / "isaacteleop" / "so101-assets"
    legacy.mkdir(parents=True)
    (legacy / "arm.stl").write_bytes(b"solid arm\n")
    (legacy / ".fetch_complete").touch()
    return legacy


def test_a_failed_fetch_names_the_override(tmp_path, monkeypatch):
    """A bare URLError tells an air-gapped operator nothing they can act on."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(assets.CACHE_ENV_VAR, raising=False)
    _refuse_to_fetch(monkeypatch)

    with pytest.raises(OSError) as excinfo:
        assets.ensure_so101_scene()

    assert assets.CACHE_ENV_VAR in str(excinfo.value)


def test_no_1_5_cache_is_claimed_when_there_is_none(tmp_path, monkeypatch):
    """On a fresh host the old directory does not exist. Saying it does is the same
    class of defect the legacy-override diagnostic was added to avoid."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(assets.CACHE_ENV_VAR, raising=False)
    _refuse_to_fetch(monkeypatch)

    with pytest.raises(OSError) as excinfo:
        assets.ensure_so101_scene()

    assert "1.5 cache" not in str(excinfo.value)
    assert not (tmp_path / "isaacteleop").exists()


def test_the_printed_recovery_command_actually_recovers_the_cache(
    tmp_path, monkeypatch
):
    """Runs what the message tells the operator to run, against the on-disk state
    the message is printed from.

    A bare `mv <old> <new>` cannot work here: _cache_dir has already created the
    destination and _copy_wrappers has already filled it, so mv nests the 1.5 cache
    inside it and exits 0 -- leaving the meshes where nothing looks, which is worse
    than the URLError this message replaced.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(assets.CACHE_ENV_VAR, raising=False)
    _refuse_to_fetch(monkeypatch)
    legacy = _populated_1_5_cache(tmp_path)

    with pytest.raises(OSError) as excinfo:
        assets.ensure_so101_scene()

    commands = re.findall(r"`([^`]+)`", str(excinfo.value))
    assert len(commands) == 1, commands
    subprocess.run(commands[0], shell=True, check=True)

    dest = assets._cache_dir(assets.CACHE_ENV_VAR, "so101-assets")
    assert (dest / "arm.stl").read_bytes() == b"solid arm\n"
    # Copied, not moved: the 1.5 cache is still there to fall back on.
    assert (legacy / "arm.stl").is_file()

    # The fetch still refuses, so this can only pass on the copied completeness
    # marker, which is a dotfile and only the trailing `/.` carries it.
    scene = assets.ensure_so101_scene()
    assert scene == (dest / assets.SCENE_FILE).resolve()
    assert scene.is_file()


def test_the_recovery_command_survives_a_space_in_the_cache_path(tmp_path, monkeypatch):
    """An unquoted command splits mid-path, and `data` beside `data backup` is an
    ordinary lab-disk shape: the prefix before the space names a directory that
    exists, so the command operates on the neighbour rather than failing outright.
    """
    neighbour = tmp_path / "data"
    neighbour.mkdir()
    (neighbour / "recordings.mcap").write_bytes(b"mcap\n")

    root = tmp_path / "data backup"
    root.mkdir()
    monkeypatch.setenv("XDG_CACHE_HOME", str(root))
    monkeypatch.delenv(assets.CACHE_ENV_VAR, raising=False)
    _refuse_to_fetch(monkeypatch)
    _populated_1_5_cache(root)

    with pytest.raises(OSError) as excinfo:
        assets.ensure_so101_scene()

    commands = re.findall(r"`([^`]+)`", str(excinfo.value))
    assert len(commands) == 1, commands
    recovery = subprocess.run(commands[0], shell=True, check=False)

    # Before the exit status, deliberately: an unquoted command destroys the
    # neighbour and *then* fails, so check=True would report only the failure and
    # the operator would conclude nothing ran.
    assert (neighbour / "recordings.mcap").is_file()
    assert recovery.returncode == 0, commands[0]

    dest = assets._cache_dir(assets.CACHE_ENV_VAR, "so101-assets")
    assert (dest / "arm.stl").read_bytes() == b"solid arm\n"


def test_a_pre_populated_rebot_cache_needs_no_completeness_marker(
    tmp_path, monkeypatch
):
    """The air-gapped path REBOT_CACHE_ENV_VAR exists for.

    The operator copies in a byte-identical tree; `.fetch_complete` is internal and
    is not among the files upstream has. The digest is the completeness proof, so
    gating the fetch on the marker alone sent that host back to the network.
    """
    cache = tmp_path / "rebot-devarm-rs-assets"
    cache.mkdir()
    (cache / "rebot.stl").write_bytes(b"solid rebot\n")
    monkeypatch.setenv(assets.REBOT_CACHE_ENV_VAR, str(cache))
    monkeypatch.setattr(
        assets, "REBOT_MANIFEST_SHA256", assets._rebot_cached_digest(cache)
    )
    _refuse_to_fetch(monkeypatch)

    scene = assets.ensure_rebot_devarm_rs_scene()

    assert scene == (cache / assets.REBOT_SCENE_FILE).resolve()
    assert (cache / ".fetch_complete").is_file()
