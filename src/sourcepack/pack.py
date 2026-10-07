"""Build and verify a source archive: files plus a manifest of hashes and provenance.

SourcePack copies files you already have. It never downloads anything, does not read PDFs,
and cannot confirm licences: `retrieved_at`, `url` and `licence` are what you wrote. The
manifest is not signed; to make tampering with it detectable, keep `manifest_sha256`
somewhere else and pass it to `verify --manifest-hash`.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .core import InputError, file_digest, finding, inside, now, report, require
from .core import digest as sha256

MANIFEST = "manifest.json"
MAX_ENTRY_BYTES = 1024 * 1024 * 1024


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def build(data: dict[str, Any], root: str | Path, archive: str | Path) -> dict[str, Any]:
    sources = require(data, "sources", list)
    if not sources:
        raise InputError("SourcePack needs at least one source")
    target = Path(archive).resolve()
    if target.exists():
        raise InputError("The archive already exists; choose a new file name")
    entries: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        relative = require(source, "path", str)
        path = inside(root, relative)
        if not path.is_file():
            raise InputError(f"Source file not found: {relative}")
        if source.get("archive_permission") is not True:
            raise InputError(
                f'{relative}: set "archive_permission": true to confirm you may copy this file'
            )
        entries.append(
            {
                **source,
                "original_path": relative,
                "archive_path": f"sources/{index:03d}/{path.name}",
                "sha256": file_digest(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {"schema_version": 1, "created_at": now(), "sources": entries}
    manifest_bytes = _manifest_bytes(manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Mode "x" refuses to overwrite, even if the file appears between the check and here.
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(MANIFEST, manifest_bytes)
        for entry in entries:
            bundle.write(inside(root, entry["original_path"]), entry["archive_path"])
    return report(
        "SourcePack",
        [
            finding(
                "BUNDLED",
                "Local copies and your metadata were archived. Keep manifest_sha256 elsewhere.",
                sources=len(entries),
            )
        ],
        archive=str(target),
        manifest_sha256=sha256(manifest_bytes),
        scope="local files you supplied; no retrieval, OCR, page extraction or licence checks",
    )


def _hash_member(bundle: zipfile.ZipFile, name: str) -> tuple[str, int]:
    import hashlib

    h, size = hashlib.sha256(), 0
    with bundle.open(name) as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            size += len(chunk)
            if size > MAX_ENTRY_BYTES:
                raise InputError(f"{name} is larger than the verification limit")
            h.update(chunk)
    return h.hexdigest(), size


def verify(
    archive: str | Path,
    manifest_hash: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        if MANIFEST not in names:
            raise InputError("The archive has no manifest.json")
        raw = bundle.read(MANIFEST)
        try:
            manifest = json.loads(raw)
            listed = manifest["sources"]
        except (ValueError, KeyError, TypeError) as exc:
            raise InputError("manifest.json is not a valid SourcePack manifest") from exc
        actual_manifest_hash = sha256(raw)
        known = {MANIFEST}
        for source in listed:
            name = source["archive_path"]
            known.add(name)
            if name not in names:
                out.append(finding("MISSING", "Listed file is not in the archive.", path=name))
                continue
            got, size = _hash_member(bundle, name)
            same = got == source["sha256"] and size == source["bytes"]
            out.append(
                finding(
                    "PASS" if same else "TAMPERED",
                    "Archived content matches the manifest."
                    if same
                    else "Archived content differs from the manifest.",
                    path=name,
                )
            )
            if root is not None and source.get("original_path"):
                original = inside(root, source["original_path"])
                if not original.is_file():
                    out.append(
                        finding(
                            "ORIGINAL_MISSING",
                            "The original file is no longer at its recorded path.",
                            path=source["original_path"],
                        )
                    )
                elif file_digest(original) != source["sha256"]:
                    out.append(
                        finding(
                            "ORIGINAL_CHANGED",
                            "The original file has changed since it was archived.",
                            path=source["original_path"],
                        )
                    )
        for name in sorted(names - known):
            if not name.endswith("/"):
                out.append(
                    finding(
                        "UNLISTED_FILE", "File in the archive is not in the manifest.", path=name
                    )
                )
    if manifest_hash:
        match = actual_manifest_hash == manifest_hash.lower()
        out.append(
            finding(
                "PASS" if match else "TAMPERED",
                "The manifest matches the hash you supplied."
                if match
                else "The manifest differs from the hash you supplied.",
                manifest_sha256=actual_manifest_hash,
            )
        )
    else:
        out.append(
            finding(
                "UNANCHORED",
                "No separately stored manifest hash was supplied, so a rewritten manifest "
                "would go unnoticed.",
                manifest_sha256=actual_manifest_hash,
            )
        )
    return report(
        "SourcePack",
        out,
        manifest_sha256=actual_manifest_hash,
        scope="integrity of archive contents only; the manifest is not independently authenticated",
    )
