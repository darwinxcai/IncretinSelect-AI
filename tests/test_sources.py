import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from incretinselect.sources import load_source_manifest, main, verify_checksum

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SourceManifestTests(unittest.TestCase):
    def test_checked_in_manifest_loads(self) -> None:
        manifest = load_source_manifest(PROJECT_ROOT / "data/manifests/sources.json")
        source_ids = {source["id"] for source in manifest["sources"]}
        self.assertIn("puszkarska_2024_training", source_ids)
        self.assertIn("puszkarska_2024_prospective_holdout", source_ids)
        self.assertIn("rcsb_structure_panel", source_ids)

    def test_packaged_manifest_and_listing_are_complete(self) -> None:
        packaged = load_source_manifest()
        checked_in = load_source_manifest(PROJECT_ROOT / "data/manifests/sources.json")
        self.assertEqual(packaged, checked_in)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--list-sources"]), 0)
        self.assertEqual(
            output.getvalue().splitlines(),
            [source["id"] for source in packaged["sources"]],
        )
        for notice in ("CITATION.cff", "DATA_LICENSE.md", "LICENSE"):
            self.assertEqual(
                (PROJECT_ROOT / notice).read_bytes(),
                (PROJECT_ROOT / "src/incretinselect/notices" / notice).read_bytes(),
            )

    def test_checksum_verification(self) -> None:
        payload = b"synthetic checksum fixture"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(payload)
            self.assertTrue(verify_checksum(path, expected))
            self.assertFalse(verify_checksum(path, "0" * 64))

    def test_manifest_contains_no_embedded_activity_records(self) -> None:
        manifest = json.loads(
            (PROJECT_ROOT / "data/manifests/sources.json").read_text(encoding="utf-8")
        )
        serialized = json.dumps(manifest)
        self.assertNotIn('"EC50_T1":', serialized)
        self.assertNotIn('"EC50_T2":', serialized)


if __name__ == "__main__":
    unittest.main()
