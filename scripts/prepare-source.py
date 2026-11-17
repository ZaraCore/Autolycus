"""Create an explicit allowlist archive for review/upload, excluding local state."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "pyproject.toml", "run.py", "compose.yaml", ".env.example", ".gitignore", ".dockerignore", ".gitattributes", "config.example.toml", "schedule.requirements.toml", "ACCEPTANCE.md", "OPERATIONS.md", "MODEL-PERFORMANCE.md", "REPORT-OPTIMIZATION.md", "REQUIREMENTS-TIMING.md"}
DIRECTORIES = ("src", "tests", "scripts/linux", "scripts/windows", "deploy", "docs", ".github")


def source_files():
    result = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    result.append(Path(__file__).resolve())
    result.append(ROOT / "config/deployment.example.toml")
    for name in DIRECTORIES:
        for path in (ROOT / name).rglob("*"):
            relative = path.relative_to(ROOT)
            if path.is_file() and not any(p in {"local", "__pycache__", ".pytest_cache", "test-data"} for p in relative.parts) and path.suffix not in {".pyc", ".db", ".dpapi"}:
                result.append(path)
    return sorted(set(result))


if __name__ == "__main__":
    destination = ROOT / "data/Autolycus-source.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for path in source_files():
            output.write(path, path.relative_to(ROOT).as_posix())
    print(destination)
