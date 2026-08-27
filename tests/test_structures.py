import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from incretinselect.structures import (
    load_structure_seeds,
    main,
    resolve_structure,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeRCSBClient:
    def entry(self, pdb_id: str) -> dict:
        return {
            "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1", "2"]},
            "rcsb_entry_info": {"resolution_combined": [2.5]},
            "rcsb_accession_info": {"initial_release_date": "2020-01-01"},
            "exptl": [{"method": "ELECTRON MICROSCOPY"}],
            "struct": {"title": "Synthetic API fixture"},
            "citation": [{"pdbx_database_id_doi": "10.1000/toy"}],
        }

    def polymer_entity(self, pdb_id: str, entity_id: str) -> dict:
        descriptions = {"1": "Glucagon receptor", "2": "Glucagon"}
        chains = {"1": ["R"], "2": ["P"]}
        return {
            "rcsb_polymer_entity": {"pdbx_description": descriptions[entity_id]},
            "rcsb_polymer_entity_container_identifiers": {
                "auth_asym_ids": chains[entity_id]
            },
        }


class StructureManifestTests(unittest.TestCase):
    def test_packaged_seed_panel_and_listing_match_repository(self) -> None:
        packaged = load_structure_seeds()
        checked_in = load_structure_seeds(PROJECT_ROOT / "configs/structure_targets.csv")
        self.assertEqual(packaged, checked_in)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--list-seeds"]), 0)
        self.assertEqual(json.loads(output.getvalue()), packaged)

    def test_seed_manifest_is_unique_and_narrowly_labeled(self) -> None:
        seeds = load_structure_seeds(PROJECT_ROOT / "configs/structure_targets.csv")
        self.assertEqual(len(seeds), 10)
        self.assertEqual(len({seed["pdb_id"] for seed in seeds}), 10)
        gipr = [seed for seed in seeds if seed["receptor"] == "GIPR"]
        self.assertTrue(gipr)
        self.assertTrue(all(seed["benchmark_role"] == "context_only" for seed in gipr))

    def test_entity_resolution(self) -> None:
        seed = {
            "pdb_id": "TEST",
            "receptor": "GCGR",
            "receptor_match": "Glucagon receptor",
            "ligand": "Glucagon",
            "ligand_match": "Glucagon",
            "benchmark_role": "native_anchor",
            "study_doi": "10.1000/fallback",
            "modification_note": "native peptide",
        }
        record = resolve_structure(seed, FakeRCSBClient())
        self.assertEqual(record["receptor_auth_chains"], "R")
        self.assertEqual(record["ligand_auth_chains"], "P")
        self.assertEqual(record["resolution_angstrom"], "2.5")
        self.assertEqual(record["study_doi"], "10.1000/toy")


if __name__ == "__main__":
    unittest.main()
