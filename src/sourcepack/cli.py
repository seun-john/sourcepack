"""Command line for SourcePack."""

from __future__ import annotations

import argparse
from typing import Any

from .fresh import fresh
from .pack import build, verify
from .runner import Command, main_wrapper, run


def _build(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return build(data, args.root, args.archive)


def _verify(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return verify(args.archive, args.manifest_hash, args.root)


def _fresh(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return fresh(data)


COMMANDS = {
    "build": Command(
        _build,
        "Copy local sources into a new archive with a hash manifest",
        frozenset({"BUNDLED"}),
        options=[
            (("--root",), {"default": ".", "help": "folder the source paths are under"}),
            (("--archive",), {"required": True, "help": "new ZIP file to create"}),
        ],
        protect=("archive",),
    ),
    "verify": Command(
        _verify,
        "Check an archive against its manifest",
        frozenset({"PASS"}),
        takes_input=False,
        options=[
            (("archive",), {"help": "archive made by `sourcepack build`"}),
            (("--manifest-hash",), {"help": "manifest_sha256 you stored separately"}),
            (("--root",), {"help": "also compare the original files under this folder"}),
        ],
        protect=("archive",),
    ),
    "fresh": Command(
        _fresh, "Flag evidence due for a re-check", frozenset({"WITHIN_REVIEW_WINDOW"})
    ),
}


def main(argv: list[str] | None = None) -> int:
    return run("sourcepack", "Verifiable source archives and evidence freshness.", COMMANDS, argv)


if __name__ == "__main__":
    main_wrapper(main)
