from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_scientific_benchmark.py"
SPEC = importlib.util.spec_from_file_location("run_scientific_benchmark", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_verify_manifest = MODULE._verify_manifest


def _write_manifest(directory, *, reference: bool = False):
    payload = b'{"paper_id":"p1"}'
    (directory / "p1.json").write_bytes(payload)
    manifest = {
        "paper_count": 1,
        "files": [
            {
                "file": "p1.json",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    if reference:
        prompt = b"blind reference prompt"
        source_pdf = directory / "source.pdf"
        source_pdf.write_bytes(b"%PDF-1.4 test")
        (directory / "REFERENCE_PROMPT.txt").write_bytes(prompt)
        manifest["files"][0].update(
            source_pdf=str(source_pdf),
            source_pdf_sha256=hashlib.sha256(source_pdf.read_bytes()).hexdigest(),
        )
        manifest.update(
            reference_type="ai_independent_blind_proxy",
            human_domain_expert_reviewed=False,
            prompt_file="REFERENCE_PROMPT.txt",
            prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        )
    else:
        manifest["immutable_prediction_snapshot"] = True
    (directory / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_manifest_verification_checks_hash_bytes_and_file_set(tmp_path):
    _write_manifest(tmp_path)
    manifest, digest = _verify_manifest(tmp_path)
    assert manifest["paper_count"] == 1
    assert len(digest) == 64

    (tmp_path / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="file set"):
        _verify_manifest(tmp_path)


def test_ai_reference_manifest_cannot_claim_human_review(tmp_path):
    _write_manifest(tmp_path, reference=True)
    _verify_manifest(tmp_path, reference=True)
    manifest_path = tmp_path / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["human_domain_expert_reviewed"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="human reviewed"):
        _verify_manifest(tmp_path, reference=True)


def test_ai_reference_manifest_checks_prompt_and_source_pdf(tmp_path):
    _write_manifest(tmp_path, reference=True)
    (tmp_path / "REFERENCE_PROMPT.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="prompt artifact changed"):
        _verify_manifest(tmp_path, reference=True)

    _write_manifest(tmp_path, reference=True)
    (tmp_path / "source.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source PDF changed"):
        _verify_manifest(tmp_path, reference=True)
