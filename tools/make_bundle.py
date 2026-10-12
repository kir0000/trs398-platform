"""Build the release packages of the program (for computers without GitHub or without the Internet).

    python tools/make_bundle.py                 # version from the file VERSION, packages into dist/
    python tools/make_bundle.py 1.2.0           # another version
    python tools/make_bundle.py --no-images     # only the small installer, no Docker images

Two zip files are made:
  * TRS398-<version>-offline.zip    everything with the Docker images inside (images/trs398-images.tar.gz): start.bat loads
                                    them, no Internet and no GitHub needed on the target computer;
  * TRS398-<version>-installer.zip  the same without images: the images are pulled from the registry (needs the Internet).
Both hold the scripts, the compose file (without `build`), db/, docs/ and a checksum file (SHA256SUMS.txt).
Docker Desktop itself is not included (it has its own installer and licence).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE_REPO = "ghcr.io/kir0000/trs398-app"
EXTRA_IMAGES = ["postgres:17", "caddy:2-alpine", "alpine/openssl:latest"]       # database and backups, HTTPS proxy, certificate generation

FILES = ["start.bat", "stop.bat", "update.bat", "backup-now.bat", "backup-now.sh", "restore.bat", "restore.sh", "lan-on.bat", "lan-off.bat",
         "https-on.bat", "https-off.bat", "language.bat", ".env.example", "LICENSE", "NOTICE.md", "README.md", "README.en.md", "VERSION"]
TREES = ["db", "tools", "docs"]
TOOLS_KEEP = {"preflight.ps1", "lang.bat", "msg.en.bat", "msg.ru.bat", "verify_backup.py", "recompute_check.py"}


def run(*cmd: str) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def release_compose(version: str) -> str:
    """docker-compose.yml of the package: the app is an image (no build context), the version comes from the file VERSION."""
    lines, out, skip = (ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines(), [], False
    for line in lines:
        if line.startswith("    build:"):
            skip = True                                  # the build block (one line or a mapping) is not in the package
            continue
        if skip and line.startswith("      "):
            continue
        skip = False
        out.append(line)
    return "\n".join(out) + "\n"


def copy_tree(src: Path, dst: Path) -> None:
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if "__pycache__" in rel.parts or p.suffix in (".pyc",) or (src.name == "docs" and (rel.parts[0] == "_preview" or p.name.startswith("sample_"))):
            continue
        if src.name == "tools" and p.is_file() and p.name not in TOOLS_KEEP:
            continue
        if p.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        else:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)


def zip_folder(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, Path(folder.name) / p.relative_to(folder))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", help="version (default: the file VERSION)")
    ap.add_argument("--no-images", action="store_true", help="only the installer without Docker images")
    ap.add_argument("--skip-build", action="store_true", help="the application image is already built (tag <repo>:<version>)")
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()
    version = args.version or (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    image = f"{IMAGE_REPO}:{version}"
    out = ROOT / args.out
    out.mkdir(exist_ok=True)

    tar_gz = None
    if not args.no_images:
        if not args.skip_build:
            run("docker", "build", "--build-arg", f"APP_VERSION={version}", "-t", image, ".")
        for extra in EXTRA_IMAGES:
            if subprocess.run(["docker", "image", "inspect", extra], capture_output=True).returncode != 0:
                run("docker", "pull", extra)
        tar = out / "trs398-images.tar"
        run("docker", "save", "-o", str(tar), image, *EXTRA_IMAGES)
        tar_gz = out / "trs398-images.tar.gz"
        with open(tar, "rb") as src, gzip.open(tar_gz, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        tar.unlink()

    def build(kind: str, with_images: bool) -> Path:
        folder = out / f"TRS398-{version}"
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        for name in FILES:
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, folder / name)
        (folder / "VERSION").write_text(version + "\n", encoding="utf-8")
        for tree in TREES:
            copy_tree(ROOT / tree, folder / tree)
        (folder / "docker-compose.yml").write_text(release_compose(version), encoding="utf-8", newline="\n")
        if with_images and tar_gz:
            (folder / "images").mkdir()
            shutil.copy2(tar_gz, folder / "images" / tar_gz.name)
        sums = [f"{sha256(p)}  {p.relative_to(folder).as_posix()}" for p in sorted(folder.rglob("*")) if p.is_file()]
        (folder / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
        target = out / f"TRS398-{version}-{kind}.zip"
        zip_folder(folder, target)
        shutil.rmtree(folder)
        print(f"{target}  {target.stat().st_size / 1e6:.1f} MB  sha256 {sha256(target)}")
        return target

    build("installer", False)
    if tar_gz:
        build("offline", True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
