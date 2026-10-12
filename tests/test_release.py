"""Release packages: the compose file of a package, the files it carries, the version of the program."""
import sys
from pathlib import Path

from tests.test_app import client, world  # noqa: F401  (fixtures are discovered here)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_package_compose_has_no_build_and_keeps_everything_else():
    import make_bundle
    text = make_bundle.release_compose("1.0.0")
    assert "build:" not in text and "context: ." not in text and "APP_VERSION" not in text
    assert "image: ${TRS_IMAGE:-ghcr.io/kir0000/trs398-app}:${TRS_VERSION:-latest}" in text
    for service in ("db:", "app:", "backup:", "https:"):
        assert f"\n  {service}" in text
    assert "./db/init:/docker-entrypoint-initdb.d:ro" in text and "container_name: trs398_app" in text
    source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "build:" in source and "APP_VERSION: ${TRS_VERSION:-dev}" in source             # the repository builds, the package does not


def test_every_file_of_a_package_exists_in_the_repository():
    import make_bundle
    missing = [f for f in make_bundle.FILES if not (ROOT / f).exists()]
    assert not missing, missing
    for tree in make_bundle.TREES:
        assert (ROOT / tree).is_dir()
    assert len(list((ROOT / "db" / "init").glob("*.sql"))) >= 17
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version.count(".") == 2 and all(part.isdigit() for part in version.split("."))


def test_scripts_load_the_images_of_a_package_and_update_without_git():
    start = (ROOT / "start.bat").read_text(encoding="utf-8")
    update = (ROOT / "update.bat").read_text(encoding="utf-8")
    for text in (start, update):
        assert r"images\trs398-images.tar.gz" in text and "docker load -i" in text and 'if exist "Dockerfile"' in text
    assert r'else if not exist "images\trs398-images.tar.gz"' in update                       # a package works without git
    assert r"db\migrate.sh" in start and r"db\migrate.sh" in update


def test_version_is_shown_and_reported(world, client):
    from app.main import app_version
    assert app_version()
    health = world["adm"].get("/healthz")
    assert health.status_code == 200 and health.json()["status"] == "ok" and health.json()["version"] == app_version()
    page = world["adm"].get("/measurements?lang=ru").text
    assert "версия " + app_version() in page
    assert "version " + app_version() in world["adm"].get("/measurements?lang=en").text


def test_the_release_workflow_builds_packages_on_a_tag():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "release:" in workflow and "startswith(github.ref, 'refs/tags/v')".lower() in workflow.lower()
    assert "tools/make_bundle.py" in workflow and "dist/*.zip" in workflow and "APP_VERSION" in workflow
