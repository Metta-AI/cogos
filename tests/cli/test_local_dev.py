from cli.local_dev import (
    apply_local_checkout_env,
    default_dashboard_ports,
    default_local_data_dir,
    resolve_dashboard_ports,
)


def test_default_local_data_dir_is_checkout_local(tmp_path):
    assert default_local_data_dir(repo_root=tmp_path) == tmp_path / ".local" / "cogos"


def test_default_dashboard_ports_are_stable_for_checkout(tmp_path):
    first = default_dashboard_ports(repo_root=tmp_path)
    second = default_dashboard_ports(repo_root=tmp_path)

    assert first == second
    assert first[0] != first[1]


def test_resolve_dashboard_ports_prefers_repo_env(tmp_path):
    (tmp_path / ".env").write_text("DASHBOARD_BE_PORT=8111\nDASHBOARD_FE_PORT=5211\n")

    assert resolve_dashboard_ports(env={}, repo_root=tmp_path) == (8111, 5211)


def test_resolve_dashboard_ports_prefers_process_env_over_repo_env(tmp_path):
    (tmp_path / ".env").write_text("DASHBOARD_BE_PORT=8111\nDASHBOARD_FE_PORT=5211\n")

    ports = resolve_dashboard_ports(
        env={"DASHBOARD_BE_PORT": "8123", "DASHBOARD_FE_PORT": "5223"},
        repo_root=tmp_path,
    )

    assert ports == (8123, 5223)


def test_apply_local_checkout_env_sets_use_local_db(tmp_path):
    env: dict[str, str] = {}

    apply_local_checkout_env(env, repo_root=tmp_path)

    assert env["USE_LOCAL_DB"] == "1"
