"""agent.local.toml：疊加在 agent.toml 之上的本機覆寫（已加入 .gitignore）。"""
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from aicam.config import ConfigFileError, deep_merge, load_settings

SHIPPED = Path(__file__).resolve().parent.parent / "config" / "agent.toml"

BASE = """
[runtime]
verify_wait = 7
max_attempts = 2
[tools]
default_enabled = true
restart_pipeline = true
[skills]
enabled = ["a", "b"]
[features]
chat = true
"""


def write(dirpath, base=BASE, local=None):
    b = dirpath / "agent.toml"
    b.write_text(base)
    if local is not None:
        (dirpath / "agent.local.toml").write_text(local)
    return str(b)


def test_local_overrides_only_what_it_lists(tmp_path):
    path = write(tmp_path, local='[runtime]\nmax_attempts = 1\n[tools]\nrestart_pipeline = false\n[skills]\nenabled = ["z"]\n')
    s = load_settings(path, env={})
    assert s.max_attempts == 1 and s.verify_wait == 7                       # 沒列出的鍵沿用基礎檔
    assert s.raw["tools"] == {"default_enabled": True, "restart_pipeline": False}   # table 逐鍵合併
    assert s.raw["skills"]["enabled"] == ["z"]                              # 清單整個取代
    assert s.raw["features"] == {"chat": True}
    assert [Path(f).name for f in s.config_files] == ["agent.toml", "agent.local.toml"]


def test_missing_local_file_is_fine(tmp_path):
    s = load_settings(write(tmp_path), env={})
    assert s.max_attempts == 2 and [Path(f).name for f in s.config_files] == ["agent.toml"]


def test_copying_agent_toml_to_local_gives_identical_settings(tmp_path):
    """使用者的作法：把 agent.toml 複製成 agent.local.toml 再改。完整複製不應改變任何行為。"""
    shutil.copy(SHIPPED, tmp_path / "agent.toml")
    base = load_settings(str(tmp_path / "agent.toml"), env={})
    shutil.copy(SHIPPED, tmp_path / "agent.local.toml")
    both = load_settings(str(tmp_path / "agent.toml"), env={})
    assert both.raw == base.raw and both.max_attempts == base.max_attempts
    text = (tmp_path / "agent.local.toml").read_text().replace("max_attempts = 2", "max_attempts = 1")
    (tmp_path / "agent.local.toml").write_text(text)
    changed = load_settings(str(tmp_path / "agent.toml"), env={})
    assert changed.max_attempts == 1 and changed.verify_wait == base.verify_wait


def test_env_var_can_point_elsewhere_or_disable(tmp_path):
    path = write(tmp_path, local="[runtime]\nmax_attempts = 1\n")
    other = tmp_path / "other.toml"
    other.write_text("[runtime]\nmax_attempts = 3\n")
    assert load_settings(path, env={"AICAM_CONFIG_LOCAL": str(other)}).max_attempts == 3
    assert load_settings(path, env={"AICAM_CONFIG_LOCAL": ""}).max_attempts == 2          # 空字串＝停用
    assert load_settings(path, env={"AICAM_CONFIG_LOCAL": str(tmp_path / "nope.toml")}).max_attempts == 2


def test_syntax_error_names_the_file(tmp_path):
    with pytest.raises(ConfigFileError, match=r"agent\.local\.toml"):
        load_settings(write(tmp_path, local="[runtime\nmax_attempts = 1"), env={})
    with pytest.raises(ConfigFileError, match=r"agent\.toml"):
        load_settings(write(tmp_path, base="[runtime\n"), env={})


def test_base_path_stays_the_anchor_for_prompts_and_skills(tmp_path):
    s = load_settings(write(tmp_path, local="[runtime]\nmax_attempts = 1\n"), env={})
    assert s.config_path == str(tmp_path / "agent.toml")                      # prompts／skills 目錄以基礎檔所在資料夾為準


def test_deep_merge_does_not_mutate_inputs():
    a, b = {"x": {"y": 1, "z": 2}, "l": [1]}, {"x": {"y": 9}, "l": [2, 3]}
    assert deep_merge(a, b) == {"x": {"y": 9, "z": 2}, "l": [2, 3]}
    assert a == {"x": {"y": 1, "z": 2}, "l": [1]}


def test_tests_ignore_a_developers_local_file():
    assert os.environ["AICAM_CONFIG_LOCAL"] == ""
    assert load_settings(str(SHIPPED), env={"AICAM_CONFIG_LOCAL": ""}).config_files == (str(SHIPPED),)


def test_local_file_is_git_ignored():
    assert "config/agent.local.toml" in (SHIPPED.parent.parent / ".gitignore").read_text().split()


def test_reload_picks_up_local_changes_and_keeps_state_on_error(d, tmp_path, monkeypatch):
    monkeypatch.delenv("AICAM_CONFIG_LOCAL", raising=False)                   # 這個測試要啟用本機覆寫
    path = write(tmp_path)
    d.s = replace(d.s, config_path=path)
    d.reload()
    assert d.s.max_attempts == 2
    (tmp_path / "agent.local.toml").write_text("[runtime]\nmax_attempts = 1\nverify_wait = 4.5\n")
    d.reload()
    assert (d.s.max_attempts, d.s.verify_wait) == (1, 4.5) and len(d.s.config_files) == 2
    (tmp_path / "agent.local.toml").write_text("[runtime\n")                   # 改壞：重載失敗，維持原設定
    with pytest.raises(ConfigFileError, match="agent.local.toml"):
        d.reload()
    assert (d.s.max_attempts, d.s.verify_wait) == (1, 4.5)


def test_reload_endpoint_reports_broken_local_file(client, d, tmp_path, monkeypatch):
    monkeypatch.delenv("AICAM_CONFIG_LOCAL", raising=False)
    path = write(tmp_path, base=BASE.replace("chat = true", "chat = true\nadmin_reload = true"))
    d.s = replace(d.s, config_path=path, raw={"features": {"admin_reload": True}})
    (tmp_path / "agent.local.toml").write_text("[runtime\n")
    r = client.post("/api/admin/reload")
    assert r.status_code == 400 and "agent.local.toml" in r.json()["detail"]
    (tmp_path / "agent.local.toml").write_text("[runtime]\nmax_attempts = 1\n")
    assert client.post("/api/admin/reload").status_code == 200 and d.s.max_attempts == 1
    caps = client.get("/api/capabilities").json()
    assert [Path(f).name for f in caps["config_files"]] == ["agent.toml", "agent.local.toml"]
    ev = d.db.q("SELECT text FROM events WHERE type='config' ORDER BY id DESC LIMIT 1")[0]["text"]
    assert "agent.local.toml" in ev
