"""Effective access and named ACL observations.

``os.access`` describes this process only. A named ACL is evidence of host
configuration, not proof that a dump or mount will succeed.
"""

from __future__ import annotations

import os
import stat
from typing import Any, Callable


def inspect_nodes(
    nodes: list[str],
    *,
    access: Callable[[str, int], bool] | None = None,
    stat_fn: Callable[[str], os.stat_result] | None = None,
    getfacl: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    access_fn = access or _default_access
    stat_impl = stat_fn or os.stat
    acl_fn = getfacl if getfacl is not None else _default_getfacl
    results = []
    for node in nodes:
        results.append(_inspect_one(node, access_fn, stat_impl, acl_fn))
    return {"nodes": results, "hardware_validated": False}


def _inspect_one(
    node: str,
    access_fn: Callable[[str, int], bool],
    stat_impl: Callable[[str], os.stat_result],
    acl_fn: Callable[[str], str | None],
) -> dict[str, Any]:
    try:
        info = stat_impl(node)
        mode = stat.S_IMODE(info.st_mode)
    except FileNotFoundError:
        return {
            "node": node,
            "status": "missing",
            "reason_code": "NODE_ABSENT",
            "read": False,
            "write": False,
            "acl_status": "not_checked",
            "named_users": [],
            "hardware_validated": False,
        }
    except OSError:
        info = None
        mode = None
    readable = bool(access_fn(node, os.R_OK))
    writable = bool(access_fn(node, os.W_OK))
    acl_text = acl_fn(node)
    if acl_text is None:
        acl_status = "unavailable"
        named_users: list[dict[str, str]] = []
    else:
        acl_status = "observed"
        named_users = _named_users(acl_text)
    if readable or writable:
        status = "observed"
        reason = None
    else:
        status = "denied"
        reason = "PERMISSION_DENIED"
    return {
        "node": node,
        "status": status,
        "reason_code": reason,
        "read": readable,
        "write": writable,
        "mode": None if mode is None else oct(mode),
        "uid": None if info is None else info.st_uid,
        "gid": None if info is None else info.st_gid,
        "acl_status": acl_status,
        "named_users": named_users,
        "hardware_validated": False,
    }


def _named_users(acl_text: str) -> list[dict[str, str]]:
    found = []
    for line in acl_text.splitlines():
        if not line.startswith("user:") or line.startswith("user::"):
            continue
        parts = line.split(":")
        if len(parts) >= 3 and parts[1]:
            found.append({"user": parts[1], "permissions": parts[2]})
    return found


def _default_access(node: str, mode: int) -> bool:
    return os.access(node, mode)


def _default_getfacl(node: str) -> str | None:
    from discdeck.commands import CommandRunner

    result = CommandRunner()(["getfacl", "-p", node], timeout=3)
    if result.code != 0:
        return None
    return result.stdout
