from __future__ import annotations

from typing import Any


def assert_phase0_unproven(snapshot: dict[str, Any]) -> None:
    assert snapshot["hardware_validated"] is False
    assert snapshot["phase"] == "3"
    assert snapshot["jobs"] == []
    assert snapshot["virtual_slots"] == []
    for module in snapshot["modules"]:
        assert module["hardware_validated"] is False
        assert module["details"]["hardware_validated"] is False
        if module["id"] not in {"physical", "images.iso", "dump.redumper"}:
            assert module["capability"] != "ready"
            assert module["effective"] != "active"
    for drive in snapshot["drives"]:
        assert drive["hardware_validated"] is False
        assert all(state == "not_run" for state in drive["operations"].values())
