# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The asset cache moved in 1.6, and both ways of noticing must still work."""

import logging

import pytest

from isaaccapture.viz.robot import assets


def test_cache_dir_is_under_the_new_name(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(assets.CACHE_ENV_VAR, raising=False)
    dest = assets._cache_dir(assets.CACHE_ENV_VAR, "so101-assets")
    assert dest == tmp_path / "isaaccapture" / "so101-assets"


#: Spelled out rather than derived: _cache_dir builds the legacy name by the same
#: substitution, so deriving it here would agree with any name at all -- including
#: one that no 1.5 operator ever exported. These four are the contract
#: docs/source/references/migration.rst tabulates.
ENV_VARS = [
    ("ISAACCAPTURE_SO101_ASSETS", "ISAACTELEOP_SO101_ASSETS"),
    ("ISAACCAPTURE_REBOT_ASSETS", "ISAACTELEOP_REBOT_ASSETS"),
]


def test_the_env_var_names_are_the_ones_documented():
    assert (assets.CACHE_ENV_VAR, assets.REBOT_CACHE_ENV_VAR) == (
        ENV_VARS[0][0],
        ENV_VARS[1][0],
    )


@pytest.mark.parametrize("env_var,legacy", ENV_VARS)
def test_a_legacy_override_warns_and_is_not_read(
    tmp_path, monkeypatch, caplog, env_var, legacy
):
    """The silent path: the fetch succeeds and the operator runs upstream geometry.

    Nothing else fires here -- no error, no missing file -- so the warning is the
    only signal that a curated site cache stopped being used.
    """
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
    monkeypatch.setenv(ENV_VARS[0][1], str(tmp_path))

    with caplog.at_level(logging.WARNING, logger=assets.LOG.name):
        dest = assets._cache_dir(assets.CACHE_ENV_VAR, "so101-assets")

    assert dest == curated
    assert caplog.text == ""


def _refuse_to_fetch(monkeypatch):
    def _refuse(_url):
        raise OSError("Temporary failure in name resolution")

    monkeypatch.setattr(assets, "_fetch", _refuse)


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


def test_a_pre_populated_rebot_cache_needs_no_completeness_marker(
    tmp_path, monkeypatch
):
    """`.fetch_complete` is internal, so it is not among the files an operator
    copies in. The digest is the completeness proof; gating on the marker alone
    sent an air-gapped host back to the network."""
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
