from __future__ import annotations

from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).parents[1]


def test_runtime_source_and_manifest_do_not_reference_docmesh_py_core() -> None:
    source_references = [
        path.relative_to(PROJECT_ROOT)
        for path in (PROJECT_ROOT / "dms").rglob("*.py")
        if "docmesh_py_core" in path.read_text(encoding="utf-8")
    ]
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]

    assert source_references == []
    assert all("docmesh-py-core" not in dependency for dependency in dependencies)
    assert not (PROJECT_ROOT / "dms" / "sdk" / "async_bridge.py").exists()
