import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from incretinselect.sources import load_source_manifest, verify_checksum

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SourceManifestTests(unittest.TestCase):
    def test_checked_in_manifest_loads(self) -> None:
        manifest = load_source_manifest(PROJECT_ROOT / "data/manifests/sources.json")
        source_ids = {source["id"] for source in manifest["sources"]}
        self.assertIn("puszkarska_2024_training", source_ids)
        self.assertIn("puszkarska_2024_prospective_holdout", source_ids)
        self.assertIn("rcsb_structure_panel", source_ids)

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
