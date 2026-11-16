"""Deploy an isolated GenVM instance for each direct test."""

from pathlib import Path

import pytest
from gltest.direct import VMContext, create_address, deploy_contract

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "grant_overlap.py"


@pytest.fixture
def registry():
    vm = VMContext()
    vm.check_pickling = True
    vm.sender = create_address("admin")
    with vm.activate():
        contract = deploy_contract(CONTRACT, vm, "Demo/Exports", sdk_version="v0.2.16")
        reviewer_a = create_address("reviewer-a")
        reviewer_b = create_address("reviewer-b")
        developer = create_address("developer")
        contract.register_program("A", reviewer_a, 100)
        contract.register_program("B", reviewer_b, 150)
        yield vm, contract, reviewer_a, reviewer_b, developer
