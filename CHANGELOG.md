# Changelog

## Unreleased

- `verify` and `fresh` reports have a `coverage` block, a one-line summary on stderr and in the HTML report. Without a manifest hash, matching files are undecided (`unanchored`); sources without usable dates are undecided.
- `--min-coverage PCT`: exit 3 when fewer than PCT percent of items were decided and nothing else failed.

## 0.1.0

First release.

- `build`: copy local sources into a ZIP with a manifest of SHA-256 hashes, sizes and the metadata you supply.
- `verify`: detect changed, missing or unlisted files in an archive, optionally against a manifest hash you stored separately and against the original files.
- `fresh`: flag evidence that is due for review under your own policy, or whose fingerprint changed.
