from __future__ import annotations

import json
import shutil
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from sourcepack.cli import main
from sourcepack.core import InputError
from sourcepack.fresh import fresh
from sourcepack.pack import build, verify


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "paper.txt").write_text("The study found X.", encoding="utf-8")
    (root / "notes.md").write_text("# notes", encoding="utf-8")
    return root


def spec(*names: str, permission: bool = True) -> dict[str, Any]:
    return {
        "sources": [
            {
                "path": n,
                "title": n,
                "url": "https://example.org/x",
                "archive_permission": permission,
            }
            for n in names
        ]
    }


def statuses(result: dict[str, Any]) -> list[str]:
    return [f["status"] for f in result["findings"]]


def make(project: Path, tmp_path: Path) -> tuple[Path, str]:
    archive = tmp_path / "pack.zip"
    result = build(spec("paper.txt", "notes.md"), project, archive)
    return archive, result["manifest_sha256"]


def test_build_and_clean_verify(project: Path, tmp_path: Path) -> None:
    archive, manifest_hash = make(project, tmp_path)
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == {
            "manifest.json",
            "sources/000/paper.txt",
            "sources/001/notes.md",
        }
    result = verify(archive, manifest_hash, project)
    assert statuses(result) == ["PASS", "PASS", "PASS"]


def test_metadata_is_kept_in_the_manifest(project: Path, tmp_path: Path) -> None:
    archive, _ = make(project, tmp_path)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
    first = manifest["sources"][0]
    assert first["url"] == "https://example.org/x" and len(first["sha256"]) == 64


def test_unanchored_is_reported_without_a_manifest_hash(project: Path, tmp_path: Path) -> None:
    archive, _ = make(project, tmp_path)
    assert statuses(verify(archive))[-1] == "UNANCHORED"


def rewrite(archive: Path, replace: dict[str, bytes], drop: tuple[str, ...] = ()) -> None:
    with zipfile.ZipFile(archive) as z:
        items = {n: z.read(n) for n in z.namelist()}
    items = {n: b for n, b in items.items() if n not in drop} | replace
    archive.unlink()
    with zipfile.ZipFile(archive, "w") as z:
        for n, b in items.items():
            z.writestr(n, b)


def test_modified_file_is_detected(project: Path, tmp_path: Path) -> None:
    archive, _ = make(project, tmp_path)
    rewrite(archive, {"sources/000/paper.txt": b"The study found Y."})
    assert statuses(verify(archive))[0] == "TAMPERED"


def test_removed_and_extra_files_are_detected(project: Path, tmp_path: Path) -> None:
    archive, _ = make(project, tmp_path)
    rewrite(archive, {"extra.txt": b"x"}, drop=("sources/001/notes.md",))
    got = statuses(verify(archive))
    assert "MISSING" in got and "UNLISTED_FILE" in got


def test_rewritten_manifest_is_caught_only_by_the_anchor(project: Path, tmp_path: Path) -> None:
    archive, manifest_hash = make(project, tmp_path)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
    manifest["sources"][0]["title"] = "forged"
    rewrite(archive, {"manifest.json": json.dumps(manifest).encode()})
    assert "TAMPERED" not in statuses(verify(archive))
    assert "TAMPERED" in statuses(verify(archive, manifest_hash))


def test_original_changed_or_missing(project: Path, tmp_path: Path) -> None:
    archive, _ = make(project, tmp_path)
    (project / "paper.txt").write_text("edited later", encoding="utf-8")
    (project / "notes.md").unlink()
    got = statuses(verify(archive, root=project))
    assert "ORIGINAL_CHANGED" in got and "ORIGINAL_MISSING" in got


def test_build_requires_explicit_permission(project: Path, tmp_path: Path) -> None:
    with pytest.raises(InputError, match="archive_permission"):
        build(spec("paper.txt", permission=False), project, tmp_path / "p.zip")


def test_build_refuses_to_overwrite(project: Path, tmp_path: Path) -> None:
    archive, _ = make(project, tmp_path)
    before = archive.read_bytes()
    with pytest.raises(InputError, match="already exists"):
        build(spec("paper.txt"), project, archive)
    assert archive.read_bytes() == before


def test_build_rejects_missing_empty_and_escaping_sources(project: Path, tmp_path: Path) -> None:
    with pytest.raises(InputError):
        build(spec("nope.txt"), project, tmp_path / "a.zip")
    with pytest.raises(InputError):
        build({"sources": []}, project, tmp_path / "b.zip")
    shutil.copy(project / "paper.txt", tmp_path / "outside.txt")
    with pytest.raises(InputError, match="escapes"):
        build(spec("../outside.txt"), project, tmp_path / "c.zip")


def test_a_source_file_is_never_overwritten_by_the_archive(project: Path) -> None:
    before = (project / "paper.txt").read_bytes()
    with pytest.raises(InputError, match="already exists"):
        build(spec("paper.txt"), project, project / "paper.txt")
    assert (project / "paper.txt").read_bytes() == before


def test_non_sourcepack_zip_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(InputError, match="no manifest"):
        verify(bad)


# -- freshness -----------------------------------------------------------------------------


def src(ident: str = "s1", **kw: Any) -> dict[str, Any]:
    return {"id": ident, "checked_at": "2026-01-01", "review_after_days": 90, **kw}


def test_review_due_boundary() -> None:
    inside_window = fresh({"as_of": "2026-03-31", "sources": [src()]})
    assert statuses(inside_window) == ["WITHIN_REVIEW_WINDOW"]
    due = fresh({"as_of": "2026-04-01", "sources": [src()]})
    assert statuses(due) == ["REVIEW_DUE"]
    assert due["findings"][0]["evidence"]["next_review"] == "2026-04-01"


def test_as_of_defaults_to_today() -> None:
    result = fresh({"sources": [src()]}, today=date(2026, 2, 1))
    assert result["as_of"] == "2026-02-01"


def test_changed_fingerprint_and_claims() -> None:
    s = src(claim_ids=["c1"], previous_fingerprint="a", current_fingerprint="b")
    result = fresh({"as_of": "2026-01-02", "sources": [s]})
    assert statuses(result) == ["WITHIN_REVIEW_WINDOW", "SOURCE_CHANGED"]
    assert result["findings"][1]["evidence"]["affected_claims"] == ["c1"]


def test_missing_data_future_date_and_empty() -> None:
    assert statuses(fresh({"as_of": "2026-01-01", "sources": [{"id": "x"}]})) == ["NEEDS_REVIEW"]
    future = fresh({"as_of": "2025-01-01", "sources": [src()]})
    assert statuses(future) == ["INVALID_DATE"]
    assert statuses(fresh({"as_of": "2026-01-01", "sources": []})) == ["NEEDS_REVIEW"]


@pytest.mark.parametrize(
    "bad",
    [
        {"as_of": "01/02/2026", "sources": []},
        {"as_of": "2026-01-01", "sources": [src(), src()]},
        {"as_of": "2026-01-01", "sources": [src(review_after_days=-1)]},
        {"as_of": "2026-01-01", "sources": [src(checked_at="soon")]},
        {"as_of": "2026-01-01", "sources": [src(claim_ids="c1")]},
    ],
)
def test_bad_freshness_input(bad: dict[str, Any]) -> None:
    with pytest.raises(InputError):
        fresh(bad)


# -- command line --------------------------------------------------------------------------


def test_cli_build_verify_and_strict(project: Path, tmp_path: Path) -> None:
    src_json = tmp_path / "in.json"
    src_json.write_text(json.dumps(spec("paper.txt")), encoding="utf-8")
    archive = tmp_path / "out.zip"
    report = tmp_path / "r.json"
    assert (
        main(
            [
                "build",
                str(src_json),
                "--root",
                str(project),
                "--archive",
                str(archive),
                "-o",
                str(report),
            ]
        )
        == 0
    )
    manifest_hash = json.loads(report.read_text(encoding="utf-8"))["manifest_sha256"]
    ok = [
        "verify",
        str(archive),
        "--manifest-hash",
        manifest_hash,
        "--root",
        str(project),
        "--strict",
        "-o",
        str(tmp_path / "v.json"),
    ]
    assert main(ok) == 0
    assert main(["verify", str(archive), "--strict", "-o", str(tmp_path / "v.json")]) == 1


def test_cli_second_build_to_same_archive_fails(project: Path, tmp_path: Path) -> None:
    src_json = tmp_path / "in.json"
    src_json.write_text(json.dumps(spec("paper.txt")), encoding="utf-8")
    args = [
        "build",
        str(src_json),
        "--root",
        str(project),
        "--archive",
        str(tmp_path / "o.zip"),
        "-o",
        str(tmp_path / "r.json"),
    ]
    assert main(args) == 0
    assert main(args) == 2


def test_cli_will_not_overwrite_the_archive_with_a_report(project: Path, tmp_path: Path) -> None:
    archive, _ = make(project, tmp_path)
    before = archive.read_bytes()
    assert main(["verify", str(archive), "-o", str(archive)]) == 2
    assert archive.read_bytes() == before


def test_cli_fresh(tmp_path: Path) -> None:
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"as_of": "2026-06-01", "sources": [src()]}), encoding="utf-8")
    assert main(["fresh", str(f), "--strict", "-o", str(tmp_path / "o.json")]) == 1
