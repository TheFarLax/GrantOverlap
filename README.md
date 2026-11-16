# GrantOverlap

GrantOverlap is a GenLayer Intelligent Contract for grant programs that fund work in the same public GitHub repository. It checks each claim against earlier funded work before crediting the recipient.

An enrolled reviewer submits a deliverable description, a full commit SHA and the changed file path. The contract retrieves that diff and records the evidence hash. It checks repeat submissions of the same commit and file directly. For materially similar work presented through a different diff, GenLayer validators independently evaluate the candidate and the funded diffs and agree on the verdict, cited claim and evidence. [GenLayer Equivalence Principle](https://docs.genlayer.com/developers/intelligent-contracts/equivalence-principle)

| Verdict | State change |
|---|---|
| `APPROVED` | Credits move from the program's demo budget to the recipient's demo balance. |
| `DUPLICATE` | The claim cites the earlier funded record and awards zero credits. |
| `NEEDS_EVIDENCE` | The contract records the reason and awards zero credits. A reviewer can submit corrected evidence under a new claim ID. |

## Studionet deployment

| Item | Value |
|---|---|
| Network | Studionet, chain ID `61999` |
| Contract | `0x3C8349789a311Fa354A6b241ac871df6FB3468b5` |
| Deployment | [Finalized transaction](https://explorer-studio.genlayer.com/tx/0x0d23fabcf8c668d2491f920c1166ded525fe1b278971c3ebaf230b407f048da6) |
| Evidence repository | `github/gitignore` |
| Source verification | On-chain source SHA-256 matches `contracts/grant_overlap.py` |

The live demo uses two sample grant programs and public commit diffs from `github/gitignore`. The claims and credits are demo data. The signer was created in memory for deployment and seeding. [Studionet network reference](https://docs.genlayer.com/developers/networks)

## Verified live claims

| Claim | Verdict | Credits awarded | Receipt |
|---|---|---:|---|
| Fund the Celery Beat ignore-rule change | `APPROVED` | 30 | [Finalized](https://explorer-studio.genlayer.com/tx/0xfa59f15055d4a5506aef925db532548c2fa52347417a71dc58c3247519056c06) |
| Submit the same commit and file under Grant B | `DUPLICATE` | 0 | [Finalized](https://explorer-studio.genlayer.com/tx/0x1853bda4a9c1ec1116195d59ba43c3f8af998056e86ac937f619ef4f7b8ac723) |
| Submit the same change using a different Git commit | `DUPLICATE` | 0 | [Finalized](https://explorer-studio.genlayer.com/tx/0x3ec00a4607297bfcc8ea8a8c41e32535265d82443dcd95858c31f974939248ea) |
| Fund the distinct LCOV ignore rule | `APPROVED` | 25 | [Finalized](https://explorer-studio.genlayer.com/tx/0xa5ab87f951f3d1e89cc6481ce33cb8e6f2bfd079f1c932060c9886ba78c28c4c) |
| Submit a file absent from the selected diff | `NEEDS_EVIDENCE` | 0 | [Finalized](https://explorer-studio.genlayer.com/tx/0x11d2630550a1561853f8bbda80f422223bc2a8e2763f2ac59388532b7fe3306a) |

The recipient earned **55 demo credits**. Grant A finished with 70 credits and Grant B with 125. Both duplicate claims refer to `funded-celery`. The two different commits in the semantic duplicate case have distinct diff digests.

Local checks passed with **14 direct-mode tests** and **3 GenVM lint checks**.

## Run locally

Use Python 3.12. The direct-mode tests fetch the pinned GenVM SDK on the first run and use mocked web and model responses for each case.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
genvm-lint lint contracts/grant_overlap.py
python -m pytest tests/direct/ -q
```

Verify the included deployment and demo from fresh on-chain reads.

```bash
python test_deployed.py
```

Run a new five-case demo on Studionet. The script saves public receipts and state summaries under `artifacts/fresh-demo/`.

```bash
python test_deployed.py --fresh
```

## Deploy with your reviewer wallet

The script registers two demo programs for your wallet. Pass the public address you want to use for signing claim submissions.

```bash
python deploy_studionet.py OWNER/REPO --reviewer YOUR_0X_WALLET_ADDRESS
```

To administer your own programs, load `contracts/grant_overlap.py` in GenLayer Studio and deploy from your selected Studionet wallet. Pass the repository as `owner/repo` to the constructor. The deploying address can register programs. [GenLayer Studio](https://studio.genlayer.com/)

## Contract interface

| Method | Use |
|---|---|
| `register_program(program_id, reviewer, budget)` | Deployer sets the program's reviewer and initial demo credits. |
| `submit_claim(program_id, claim_id, recipient, credits, description, commit_sha, file_path)` | Program reviewer submits a claim and authorizes its recipient and amount. |
| `get_claim(claim_id)` | Get the decision, reason, award, matched claim ID, pinned GitHub commit and diff digest. |
| `get_program(program_id)` | Get the reviewer and current remaining budget. |
| `get_credit_balance(recipient)` | Get the recipient's total awarded demo credits. |
| `get_funded_claim_ids()` | List the funded claims used during overlap evaluation. |
| `get_repository()` | Get the GitHub repository bound to this deployment. |

The current version evaluates one public repository, one textual file diff per claim and up to eight funded claims. Each supported diff is at most 4,000 UTF-8 bytes. The contract uses the funded history as the comparison set. Read finalized state for settled credits.

## Repository contents

| Path | Purpose |
|---|---|
| `contracts/grant_overlap.py` | Deployed Intelligent Contract |
| `deploy_studionet.py` | Deployment and source verification |
| `tests/conftest.py` and `tests/direct/` | Local contract and validator tests |
| `test_deployed.py` | Read-only live verifier and fresh demo runner |
| `deployment_info.json` | Finalized deployment receipt and matching source hashes |
| `test_report.json` | Live transaction hashes, claim verdicts and finalized credit balances |
| `requirements.txt` | Pinned tooling versions |
