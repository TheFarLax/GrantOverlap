from hashlib import sha256
import json

import pytest

FILE = "src/export.py"
CSV_COMMIT = "a" * 40
RESTATED_COMMIT = "b" * 40
PDF_COMMIT = "c" * 40
CSV_PATCH = "@@ -1 +1 @@\n-export()\n+export_csv()"
RESTATED_PATCH = "@@ -20 +20 @@\n-make_report()\n+write_csv_report()"
PDF_PATCH = "@@ -5 +5 @@\n-report()\n+export_pdf()"
URL_PATTERN = r"api\.github\.com/repos/demo/exports/commits/"


def mock_patch(
    vm, commit, patch, *, status=200, additions=1, deletions=1, file_path=FILE, sha=None
):
    vm.mock_web(URL_PATTERN + commit + "$", {
        "status": status,
        "body": json.dumps({
            "sha": sha or commit,
            "files": [{
                "filename": file_path,
                "patch": patch,
                "additions": additions,
                "deletions": deletions,
            }],
        }),
    })


def mock_judgment(vm, verdict, match=""):
    vm.mock_llm("Apply this fixed grant policy", json.dumps({
        "verdict": verdict, "matched_claim_id": match,
    }))


def approve_csv(registry):
    vm, contract, reviewer_a, _, recipient = registry
    mock_patch(vm, CSV_COMMIT, CSV_PATCH)
    mock_judgment(vm, "APPROVED")
    with vm.prank(reviewer_a):
        verdict = contract.submit_claim("A", "csv", recipient, 30, "CSV export", CSV_COMMIT, FILE)
    assert verdict == "APPROVED", contract.get_claim("csv")
    assert vm.run_validator()
    vm.clear_mocks()


def test_approve_distinct_work_in_same_file_and_record_credits(registry):
    vm, contract, _, reviewer_b, recipient = registry
    approve_csv(registry)
    mock_patch(vm, PDF_COMMIT, PDF_PATCH)
    mock_judgment(vm, "APPROVED")
    with vm.prank(reviewer_b):
        verdict = contract.submit_claim("B", "pdf", recipient, 25, "PDF export", PDF_COMMIT, FILE)
    assert verdict == "APPROVED"
    assert vm.run_validator()
    assert contract.get_credit_balance(recipient) == 55
    assert contract.get_funded_claim_ids() == ["csv", "pdf"]
    assert contract.get_program("A")["remaining"] == 70
    assert contract.get_program("B")["remaining"] == 125
    assert contract.get_claim("pdf")["patch_sha256"] == sha256(PDF_PATCH.encode()).hexdigest()
    assert contract.get_claim("pdf")["commit_url"].endswith(PDF_COMMIT)
    assert contract.get_repository() == "demo/exports"


def test_duplicate_commit_and_file_without_web_or_model(registry):
    vm, contract, _, reviewer_b, recipient = registry
    approve_csv(registry)
    vm.clear_validators()
    with vm.prank(reviewer_b):
        verdict = contract.submit_claim("B", "restated", recipient, 20, "Reporting module", CSV_COMMIT, FILE)
    assert verdict == "DUPLICATE"
    assert contract.get_claim("restated")["matched_claim_id"] == "csv"
    assert contract.get_claim("restated")["awarded_credits"] == 0
    assert contract.get_credit_balance(recipient) == 30
    assert contract.get_program("B")["remaining"] == 150
    with pytest.raises(RuntimeError, match="No validator captured"):
        vm.run_validator()


def test_identical_file_diff_in_another_commit(registry):
    vm, contract, _, reviewer_b, recipient = registry
    approve_csv(registry)
    mock_patch(vm, RESTATED_COMMIT, CSV_PATCH)
    with vm.prank(reviewer_b):
        verdict = contract.submit_claim("B", "reapplied", recipient, 20, "Reports", RESTATED_COMMIT, FILE)
    assert verdict == "DUPLICATE"
    assert "same patch" in contract.get_claim("reapplied")["reason"]
    assert vm.run_validator()


def test_semantic_overlap_and_consensus_disagreement(registry):
    vm, contract, _, reviewer_b, recipient = registry
    approve_csv(registry)
    mock_patch(vm, RESTATED_COMMIT, RESTATED_PATCH)
    mock_judgment(vm, "DUPLICATE", "csv")
    with vm.prank(reviewer_b):
        verdict = contract.submit_claim("B", "reports", recipient, 20, "Reporting module", RESTATED_COMMIT, FILE)
    assert verdict == "DUPLICATE"
    assert contract.get_claim("reports")["matched_claim_id"] == "csv"
    assert vm.run_validator()
    vm.clear_mocks()
    mock_patch(vm, RESTATED_COMMIT, RESTATED_PATCH)
    mock_judgment(vm, "APPROVED")
    assert not vm.run_validator()


@pytest.mark.parametrize("status,additions,path,sha", [
    (404, 1, FILE, CSV_COMMIT),
    (429, 1, FILE, CSV_COMMIT),
    (200, 2, FILE, CSV_COMMIT),
    (200, 1, "different.py", CSV_COMMIT),
    (200, 1, FILE, PDF_COMMIT),
])
def test_missing_or_incomplete_evidence(registry, status, additions, path, sha):
    vm, contract, reviewer, _, recipient = registry
    mock_patch(vm, CSV_COMMIT, CSV_PATCH, status=status, additions=additions, file_path=path, sha=sha)
    with vm.prank(reviewer):
        verdict = contract.submit_claim("A", "bad-evidence", recipient, 30, "CSV export", CSV_COMMIT, FILE)
    assert verdict == "NEEDS_EVIDENCE"
    assert contract.get_credit_balance(recipient) == 0
    assert contract.get_program("A")["remaining"] == 100
    assert vm.run_validator()


def test_model_cannot_cite_unknown_prior_claim(registry):
    vm, contract, reviewer, _, recipient = registry
    mock_patch(vm, CSV_COMMIT, CSV_PATCH)
    mock_judgment(vm, "DUPLICATE", "unfunded-id")
    with vm.prank(reviewer):
        verdict = contract.submit_claim("A", "invalid", recipient, 30, "CSV export", CSV_COMMIT, FILE)
    assert verdict == "NEEDS_EVIDENCE"
    assert contract.get_funded_claim_ids() == []


def test_reviewer_scope_budget_and_replay(registry):
    vm, contract, reviewer_a, reviewer_b, recipient = registry
    with vm.prank(reviewer_b):
        with vm.expect_revert("Only the deployer"):
            contract.register_program("unapproved", reviewer_b, 100)
        with vm.expect_revert("Only this program's reviewer"):
            contract.submit_claim("A", "x", recipient, 20, "CSV export", CSV_COMMIT, FILE)
    approve_csv(registry)
    with vm.prank(reviewer_a):
        with vm.expect_revert("within the program budget"):
            contract.submit_claim("A", "over-budget", recipient, 71, "PDF export", PDF_COMMIT, FILE)
        with vm.expect_revert("new claim ID"):
            contract.submit_claim("A", "csv", recipient, 30, "CSV export", CSV_COMMIT, FILE)
    assert contract.get_credit_balance(recipient) == 30
    assert contract.get_program("A")["remaining"] == 70


def test_validator_rejects_different_patch_for_same_verdict(registry):
    vm, contract, reviewer, _, recipient = registry
    mock_patch(vm, CSV_COMMIT, CSV_PATCH)
    mock_judgment(vm, "APPROVED")
    with vm.prank(reviewer):
        assert contract.submit_claim(
            "A", "csv", recipient, 30, "CSV export", CSV_COMMIT, FILE
        ) == "APPROVED"
    assert vm.run_validator()
    vm.clear_mocks()
    mock_patch(vm, CSV_COMMIT, PDF_PATCH)
    mock_judgment(vm, "APPROVED")
    assert not vm.run_validator()


def test_unsubstantiated_claim_can_be_resubmitted_with_corrected_evidence(registry):
    vm, contract, reviewer, _, recipient = registry
    mock_patch(vm, PDF_COMMIT, PDF_PATCH)
    mock_judgment(vm, "NEEDS_EVIDENCE")
    with vm.prank(reviewer):
        assert contract.submit_claim(
            "A", "insufficient", recipient, 30, "CSV export", PDF_COMMIT, FILE
        ) == "NEEDS_EVIDENCE"
    assert contract.get_credit_balance(recipient) == 0
    vm.clear_mocks()
    approve_csv(registry)
    assert contract.get_claim("insufficient")["verdict"] == "NEEDS_EVIDENCE"
    assert contract.get_credit_balance(recipient) == 30


def test_full_registry_keeps_balances_and_funded_history(registry):
    vm, contract, reviewer_a, _, recipient = registry
    mock_judgment(vm, "APPROVED")
    with vm.prank(reviewer_a):
        for index in range(8):
            commit = f"{index:040x}"
            mock_patch(vm, commit, f"@@ -1 +1 @@\n-old()\n+feature_{index}()")
            assert contract.submit_claim(
                "A", f"work-{index}", recipient, 1, f"Feature {index}", commit, FILE,
            ) == "APPROVED"
        mock_patch(vm, PDF_COMMIT, PDF_PATCH)
        with vm.expect_revert("funded-claim limit"):
            contract.submit_claim("A", "extra", recipient, 1, "PDF export", PDF_COMMIT, FILE)
    assert len(contract.get_funded_claim_ids()) == 8
    assert contract.get_credit_balance(recipient) == 8
    assert contract.get_program("A")["remaining"] == 92
