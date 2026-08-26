# Raw data

This directory is intentionally gitignored. Use `scripts/fetch_public_data.py` to
download commit-pinned upstream workbooks and verify their checksums. Do not edit
or redistribute upstream data without preserving provenance and license notices.

`make fetch` retrieves both the 125-record training source and the official
P1–P15 prospective workbooks. File names, URLs, roles, checksums, and licenses are
defined in `../manifests/sources.json`.
