"""Verify the packaged Studionet demo, or deploy and test a fresh one."""

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from genlayer_py import create_account
from genlayer_py.types import CalldataAddress

from deploy_studionet import (
    DEMO_REPOSITORY,
    EXPLORER,
    ROOT,
    SOURCE,
    check_network,
    connect,
    deploy,
    funded_client,
    onchain_source_hash,
    read_finalized,
    receipt_summary,
    rpc,
    verify_execution,
    wait_finalized,
    write_json,
)

PROGRAMS = {"grant-a": 100, "grant-b": 150}
CELERY_COMMIT = "2a4ac93e7906d35e962cdf70fea80f92f98da1ed"
REPEATED_COMMIT = "576334520435382d6522f349b9d270eda1e79a25"
COVERAGE_COMMIT = "cd33ea10e8ce2524c06530a9d9a3628644be70b7"
FILE_PATH = "Python.gitignore"


@dataclass(frozen=True)
class Case:
    claim_id: str
    program: str
    credits: int
    description: str
    commit: str
    verdict: str
    match: str = ""
    path: str = FILE_PATH


CASES = (
    Case(
        "funded-celery", "grant-a", 30,
        "Add a wildcard to the celerybeat-schedule ignore rule to cover all generated schedule files.",
        CELERY_COMMIT, "APPROVED",
    ),
    Case(
        "duplicate-commit", "grant-b", 30,
        "Expand the ignore rule for generated Celery Beat schedules.",
        CELERY_COMMIT, "DUPLICATE", "funded-celery",
    ),
    Case(
        "duplicate-work", "grant-b", 30,
        "Ignore Celery Beat schedule files that share the same filename prefix.",
        REPEATED_COMMIT, "DUPLICATE", "funded-celery",
    ),
    Case(
        "funded-coverage", "grant-b", 25,
        "Ignore generated LCOV coverage files using the *.lcov pattern.",
        COVERAGE_COMMIT, "APPROVED",
    ),
    Case(
        "missing-file", "grant-b", 20,
        "Record an export implementation in the manifest.",
        COVERAGE_COMMIT, "NEEDS_EVIDENCE", path="missing-manifest.json",
    ),
)


def equal(label, actual, expected):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def check_claim(client, address, recipient, case):
    claim = read_finalized(client, address, "get_claim", case.claim_id)
    award = case.credits if case.verdict == "APPROVED" else 0
    expected = {
        "program_id": case.program,
        "requested_credits": case.credits,
        "description": case.description,
        "verdict": case.verdict,
        "matched_claim_id": case.match,
        "awarded_credits": award,
        "commit_url": f"https://github.com/{DEMO_REPOSITORY}/commit/{case.commit}",
        "file_path": case.path,
    }
    for field, value in expected.items():
        equal(f"{case.claim_id}.{field}", claim[field], value)
    equal(f"{case.claim_id}.recipient", claim["recipient"].lower(), recipient.lower())
    digest = claim["patch_sha256"]
    if case.verdict == "NEEDS_EVIDENCE":
        equal(f"{case.claim_id}.patch_sha256", digest, "")
    elif not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AssertionError(f"{case.claim_id}.patch_sha256 is incomplete")
    return claim


def check_balances(client, address, recipient):
    expected_remaining = PROGRAMS.copy()
    funded_ids = []
    for case in CASES:
        if case.verdict == "APPROVED":
            expected_remaining[case.program] -= case.credits
            funded_ids.append(case.claim_id)
    program_records = {}
    for program, remaining in expected_remaining.items():
        record = read_finalized(client, address, "get_program", program)
        equal(f"{program}.budget", record["budget"], PROGRAMS[program])
        equal(f"{program}.remaining", record["remaining"], remaining)
        equal(f"{program}.reviewer", record["reviewer"].lower(), recipient.lower())
        program_records[program] = record
    total = sum(PROGRAMS.values()) - sum(expected_remaining.values())
    equal(
        "finalized credit balance",
        read_finalized(client, address, "get_credit_balance", CalldataAddress(recipient)),
        total,
    )
    equal(
        "funded claim history",
        read_finalized(client, address, "get_funded_claim_ids"),
        funded_ids,
    )
    return {"demo_credit_balance": total, "programs": program_records, "funded_ids": funded_ids}


def check_duplicate_digests(claims):
    baseline = claims["funded-celery"]["patch_sha256"]
    equal("same commit uses the funded diff digest", claims["duplicate-commit"]["patch_sha256"], baseline)
    if claims["duplicate-work"]["patch_sha256"] == baseline:
        raise AssertionError("The semantic duplicate case requires a different diff digest.")


def submit_finalized(client, address, method, args, label, report, output_path):
    tx_hash = client.write_contract(
        address=address, function_name=method, args=args, leader_only=False
    )
    report["transactions"][label] = {
        "tx_hash": tx_hash,
        "explorer_url": f"{EXPLORER}/tx/{tx_hash}",
    }
    write_json(output_path, report)
    print(f"{label}: {tx_hash}", flush=True)
    summary = receipt_summary(tx_hash, wait_finalized(tx_hash))
    report["transactions"][label] = summary
    write_json(output_path, report)
    verify_execution(summary)


def run_fresh(output_dir):
    client = funded_client()
    info = deploy(client, DEMO_REPOSITORY, output_dir)
    address = info["contract_address"]
    recipient = client.local_account.address
    wallet_argument = CalldataAddress(recipient)
    output_path = output_dir / "test_report.json"
    report = {
        "network": info["network"],
        "chain_id": info["chain_id"],
        "contract_address": address,
        "repository": DEMO_REPOSITORY,
        "demo_reviewer_and_recipient": recipient,
        "transactions": {},
        "claims": {},
    }
    for program, budget in PROGRAMS.items():
        submit_finalized(
            client, address, "register_program", [program, wallet_argument, budget],
            f"register-{program}", report, output_path,
        )
        record = read_finalized(client, address, "get_program", program)
        equal(f"{program}.remaining", record["remaining"], budget)

    for case in CASES:
        submit_finalized(
            client, address, "submit_claim",
            [
                case.program, case.claim_id, wallet_argument, case.credits,
                case.description, case.commit, case.path,
            ],
            case.claim_id, report, output_path,
        )
        try:
            claim = check_claim(client, address, recipient, case)
        except AssertionError:
            report["claims"][case.claim_id] = read_finalized(
                client, address, "get_claim", case.claim_id
            )
            write_json(output_path, report)
            raise
        report["claims"][case.claim_id] = claim
        write_json(output_path, report)
        print(f"PASS {case.claim_id}: {claim['verdict']} ({claim['reason']})", flush=True)

    check_duplicate_digests(report["claims"])
    report["finalized_balances"] = check_balances(client, address, recipient)
    report["passed_claim_cases"] = len(CASES)
    write_json(output_path, report)
    print(f"{len(CASES)}/{len(CASES)} live claim cases passed.", flush=True)


def verify_existing(output_dir):
    info = json.loads((output_dir / "deployment_info.json").read_text(encoding="utf-8"))
    report = json.loads((output_dir / "test_report.json").read_text(encoding="utf-8"))
    address = info["contract_address"]
    equal("report contract address", report["contract_address"], address)
    check_network()
    client = connect(create_account())
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    equal("reported source hash", info["source_sha256"], source_hash)
    equal("on-chain source hash", onchain_source_hash(address), source_hash)
    equal("finalized repository", read_finalized(client, address, "get_repository"), DEMO_REPOSITORY)
    receipts = {"deploy": info["deploy_tx"], **report["transactions"]}
    equal("receipt count", len(receipts), len(PROGRAMS) + len(CASES) + 1)
    for label, summary in receipts.items():
        tx_hash = summary["tx_hash"]
        receipt = rpc("eth_getTransactionByHash", [tx_hash])
        equal(f"{label}.contract_address", receipt["to_address"].lower(), address.lower())
        verify_execution(receipt_summary(tx_hash, receipt))

    recipient = report["demo_reviewer_and_recipient"]
    for case in CASES:
        claim = check_claim(client, address, recipient, case)
        equal(f"{case.claim_id}.snapshot", claim, report["claims"][case.claim_id])
        print(f"PASS {case.claim_id}: {claim['verdict']}", flush=True)
    check_duplicate_digests(report["claims"])
    equal("balance snapshot", check_balances(client, address, recipient), report["finalized_balances"])
    print(f"{len(CASES)}/{len(CASES)} live claim cases verified at {address}.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true", help="Deploy a new funded test registry.")
    parser.add_argument("--output-dir", type=Path, help="Directory for the two JSON reports.")
    args = parser.parse_args()
    if args.fresh:
        run_fresh(args.output_dir or ROOT / "artifacts" / "fresh-demo")
    else:
        verify_existing(args.output_dir or ROOT)


if __name__ == "__main__":
    main()
