"""Container configuration and project persistence, without building an image."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent


@pytest.mark.parametrize("port", [None, "18000"])
def test_compose_is_local_and_uses_persistent_project_storage(tmp_path, port):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker CLI is not installed; no engine is needed for this check")

    # Never resolve the developer's actual env_file or Docker credentials.
    # The copied Compose file points to an absent, optional file in tmp_path.
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text((REPO / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    docker_config = tmp_path / "docker-config"
    docker_config.mkdir()
    environment = os.environ.copy()
    environment["DOCKER_CONFIG"] = str(docker_config)
    environment.pop("MONEYGRAPH_PORT", None)
    environment.pop("COMPOSE_FILE", None)
    environment.pop("COMPOSE_ENV_FILES", None)
    if port:
        environment["MONEYGRAPH_PORT"] = port
    available = subprocess.run([docker, "compose", "version"], env=environment,
                               capture_output=True, text=True, timeout=30, check=False)
    if available.returncode:
        pytest.skip("Docker Compose plugin is unavailable")
    result = subprocess.run([
        docker, "compose", "--project-name", "moneygraph-config-test",
        "--env-file", str(empty_env), "-f", str(compose_file), "config", "--format", "json",
    ], env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, "Docker Compose rejected the isolated configuration"
    config = json.loads(result.stdout)
    app = config["services"]["app"]
    assert app["ports"][0]["host_ip"] == "127.0.0.1"
    assert app["ports"][0]["target"] == 8000
    assert str(app["ports"][0]["published"]) == (port or "8000")
    assert set(app["environment"]) == {"MONEY_GRAPH_PROJECTS"}
    assert app["environment"]["MONEY_GRAPH_PROJECTS"] == "/data/projects"
    assert any(volume["type"] == "volume" and volume["source"] == "moneygraph_data"
               and volume["target"] == "/data" for volume in app["volumes"])
    assert "moneygraph_data" in config["volumes"]


def test_project_state_survives_process_restart_under_configured_volume_path(tmp_path):
    environment = os.environ.copy()
    environment["MONEY_GRAPH_PROJECTS"] = str(tmp_path / "mounted-volume" / "projects")
    environment["PYTHONPATH"] = str(PROJECT)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    create = """
import json
from api import storage
project = storage.create('Container persistence fixture')
folder = storage.folder(project['id'])
(folder / 'raw').mkdir()
(folder / 'raw' / 'upload.csv').write_text('src,dst,amount\\na,b,10\\n', encoding='utf-8')
storage.write(folder / 'results' / 'fixture-result' / 'summary.json', {'nodes': 2})
storage.write(folder / 'current.json', {'hash': 'fixture-result'})
print(json.dumps({'id': project['id'], 'path': str(folder)}))
"""
    first = subprocess.run([sys.executable, "-c", create], env=environment, cwd=tmp_path,
                           capture_output=True, text=True, timeout=30, check=True)
    created = json.loads(first.stdout)
    assert Path(created["path"]).parent == Path(environment["MONEY_GRAPH_PROJECTS"])
    restore = """
import json, sys
from api import storage
folder = storage.folder(sys.argv[1])
print(json.dumps({
    'name': storage.read(folder / 'project.json')['name'],
    'raw': (folder / 'raw' / 'upload.csv').read_text(encoding='utf-8'),
    'nodes': storage.read(storage.result_dir(folder) / 'summary.json')['nodes'],
}))
"""
    second = subprocess.run([sys.executable, "-c", restore, created["id"]], env=environment, cwd=tmp_path,
                            capture_output=True, text=True, timeout=30, check=True)
    restored = json.loads(second.stdout)
    assert restored == {
        "name": "Container persistence fixture", "raw": "src,dst,amount\na,b,10\n", "nodes": 2,
    }
