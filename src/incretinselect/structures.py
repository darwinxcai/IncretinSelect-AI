"""Resolve a curated peptide-GPCR seed panel against the official RCSB Data API."""

from __future__ import annotations

import argparse
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable
from urllib.request import urlopen

API_ROOT = "https://data.rcsb.org/rest/v1/core"
OUTPUT_FIELDS = [
    "pdb_id",
    "receptor",
    "ligand",
    "benchmark_role",
    "experimental_method",
    "resolution_angstrom",
    "title",
    "initial_release_date",
    "receptor_entity_id",
    "receptor_auth_chains",
    "ligand_entity_id",
    "ligand_auth_chains",
    "study_doi",
    "pdb_doi",
    "coordinate_url",
    "modification_note",
    "query_status",
]


class StructureManifestError(RuntimeError):
    """Raised when a seed cannot be resolved unambiguously."""


class RCSBClient:
    def __init__(self, api_root: str = API_ROOT, timeout: int = 30) -> None:
        self.api_root = api_root.rstrip("/")
        self.timeout = timeout

    def _get(self, route: str) -> dict[str, Any]:
        with urlopen(f"{self.api_root}/{route}", timeout=self.timeout) as response:  # noqa: S310
            return json.load(response)

    def entry(self, pdb_id: str) -> dict[str, Any]:
        return self._get(f"entry/{pdb_id}")

    def polymer_entity(self, pdb_id: str, entity_id: str) -> dict[str, Any]:
        return self._get(f"polymer_entity/{pdb_id}/{entity_id}")


def load_structure_seeds(path: str | Path | None = None) -> list[dict[str, str]]:
    required = {
        "pdb_id",
        "receptor",
        "receptor_match",
        "ligand",
        "ligand_match",
        "benchmark_role",
        "study_doi",
        "modification_note",
    }
    if path is None:
        text = files("incretinselect").joinpath("resources/structure_targets.csv").read_text(
            encoding="utf-8"
        )
    else:
        text = Path(path).read_text(encoding="utf-8")
    with io.StringIO(text, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise StructureManifestError(f"Seed CSV is missing columns: {', '.join(missing)}")
        seeds = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    ids = [seed["pdb_id"].upper() for seed in seeds]
    if any(len(pdb_id) != 4 for pdb_id in ids) or len(ids) != len(set(ids)):
        raise StructureManifestError("PDB IDs must be four characters and unique")
    for seed, pdb_id in zip(seeds, ids, strict=True):
        seed["pdb_id"] = pdb_id
    return seeds


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split())


def _description(entity: dict[str, Any]) -> str:
    return str(entity.get("rcsb_polymer_entity", {}).get("pdbx_description", ""))


def find_entity(
    entities: Iterable[tuple[str, dict[str, Any]]],
    match_text: str,
    excluded_ids: set[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    excluded = excluded_ids or set()
    candidates = [(entity_id, entity) for entity_id, entity in entities if entity_id not in excluded]
    target = _normalized(match_text)
    exact = [item for item in candidates if _normalized(_description(item[1])) == target]
    matches = exact or [item for item in candidates if target in _normalized(_description(item[1]))]
    if len(matches) != 1:
        descriptions = "; ".join(f"{eid}:{_description(entity)}" for eid, entity in candidates)
        raise StructureManifestError(
            f"Expected one entity matching {match_text!r}; found {len(matches)}. Entities: {descriptions}"
        )
    return matches[0]


def _auth_chains(entity: dict[str, Any]) -> str:
    identifiers = entity.get("rcsb_polymer_entity_container_identifiers", {})
    return ";".join(identifiers.get("auth_asym_ids", []))


def resolve_structure(seed: dict[str, str], client: RCSBClient) -> dict[str, str]:
    pdb_id = seed["pdb_id"]
    entry = client.entry(pdb_id)
    entity_ids = entry["rcsb_entry_container_identifiers"]["polymer_entity_ids"]
    entities = [(entity_id, client.polymer_entity(pdb_id, entity_id)) for entity_id in entity_ids]
    receptor_id, receptor_entity = find_entity(entities, seed["receptor_match"])
    ligand_id, ligand_entity = find_entity(
        entities, seed["ligand_match"], excluded_ids={receptor_id}
    )

    resolution_values = entry.get("rcsb_entry_info", {}).get("resolution_combined") or []
    methods = [experiment.get("method", "") for experiment in entry.get("exptl", [])]
    accession = entry.get("rcsb_accession_info", {})
    citation_doi = ""
    for citation in entry.get("citation", []):
        if citation.get("pdbx_database_id_doi"):
            citation_doi = citation["pdbx_database_id_doi"]
            break
    study_doi = citation_doi or seed["study_doi"]

    return {
        "pdb_id": pdb_id,
        "receptor": seed["receptor"],
        "ligand": seed["ligand"],
        "benchmark_role": seed["benchmark_role"],
        "experimental_method": ";".join(methods),
        "resolution_angstrom": str(resolution_values[0]) if resolution_values else "",
        "title": entry.get("struct", {}).get("title", ""),
        "initial_release_date": accession.get("initial_release_date", ""),
        "receptor_entity_id": receptor_id,
        "receptor_auth_chains": _auth_chains(receptor_entity),
        "ligand_entity_id": ligand_id,
        "ligand_auth_chains": _auth_chains(ligand_entity),
        "study_doi": study_doi,
        "pdb_doi": f"10.2210/pdb{pdb_id}/pdb",
        "coordinate_url": f"https://files.rcsb.org/download/{pdb_id}.cif",
        "modification_note": seed["modification_note"],
        "query_status": "resolved",
    }


def build_structure_manifest(
    seeds: Iterable[dict[str, str]],
    client: RCSBClient,
    strict: bool = False,
    workers: int = 4,
) -> list[dict[str, str]]:
    seed_records = list(seeds)

    def resolve_or_record_error(seed: dict[str, str]) -> dict[str, str]:
        try:
            return resolve_structure(seed, client)
        except Exception as exc:
            if strict:
                raise
            fallback = {field: "" for field in OUTPUT_FIELDS}
            fallback.update(
                {
                    "pdb_id": seed["pdb_id"],
                    "receptor": seed["receptor"],
                    "ligand": seed["ligand"],
                    "benchmark_role": seed["benchmark_role"],
                    "study_doi": seed["study_doi"],
                    "pdb_doi": f"10.2210/pdb{seed['pdb_id']}/pdb",
                    "coordinate_url": f"https://files.rcsb.org/download/{seed['pdb_id']}.cif",
                    "modification_note": seed["modification_note"],
                    "query_status": f"error: {type(exc).__name__}: {exc}",
                }
            )
            return fallback

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        return list(executor.map(resolve_or_record_error, seed_records))


def write_structure_manifest(records: Iterable[dict[str, str]], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        metavar="PATH",
        help="Seed CSV (default: packaged curated structure panel)",
    )
    parser.add_argument("--output")
    parser.add_argument(
        "--list-seeds",
        action="store_true",
        help="List the packaged seed panel without querying RCSB",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Abort if any RCSB entry cannot be resolved"
    )
    parser.add_argument("--workers", type=int, default=4, help="Concurrent RCSB entry queries")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    seeds = load_structure_seeds(args.seed)
    if args.list_seeds:
        print(json.dumps(seeds, indent=2))
        return 0
    if not args.output:
        parser.error("--output is required unless --list-seeds is used")
    records = build_structure_manifest(
        seeds,
        RCSBClient(),
        strict=args.strict,
        workers=args.workers,
    )
    write_structure_manifest(records, args.output)
    unresolved = sum(record["query_status"] != "resolved" for record in records)
    print(f"Wrote {len(records)} records to {args.output}; unresolved={unresolved}")
    return 1 if unresolved else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
