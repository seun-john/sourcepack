# Changelog

## 0.1.0

First release.

- `build`: copy local sources into a ZIP with a manifest of SHA-256 hashes, sizes and the metadata you supply.
- `verify`: detect changed, missing or unlisted files in an archive, optionally against a manifest hash you stored separately and against the original files.
- `fresh`: flag evidence that is due for review under your own policy, or whose fingerprint changed.
