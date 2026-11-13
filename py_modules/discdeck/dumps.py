"""Explicit Redumper preservation jobs.

The frontend chooses a drive and an output folder. DiscDeck selects the sg
node from that drive's sysfs identity, refuses overwrite, and records the
process. A zero exit code is not a verified dump.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import signal
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from discdeck.commands import open_pty_pair
from discdeck.models import envelope_error, envelope_ok
from discdeck.security import assert_dump_argv

MIN_FREE_BYTES = 64 * 1024 * 1024
MAX_LOG_BYTES = 1_048_576
ACTIVE_STATES = {"queued", "preflight", "running", "cancel_requested", "orphaned_running"}
_IMAGE_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DUMPJOB_DIR = re.compile(r"^dumpjob_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}(?:_[0-9]+)?$")


def validate_image_name(raw: str) -> str:
    if not isinstance(raw, str) or _IMAGE_NAME_OK.fullmatch(raw) is None:
        raise ValueError("The image name must be letters, numbers, dots, underscores, or hyphens.")
    return raw


def validate_output_root(raw: str) -> Path:
    if not isinstance(raw, str) or raw == "" or "\x00" in raw or "\n" in raw:
        raise ValueError("The output folder is empty or contains unsupported characters.")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("The output folder must be absolute.")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        if part in {"", ".", ".."}:
            raise ValueError("The output folder contains a parent segment.")
        current = current / part
        if current.is_symlink():
            raise ValueError("The output folder contains a symlink. Choose the resolved folder.")
    if not current.is_dir():
        raise ValueError("The output folder is not a directory.")
    return current


def version_argv(binary: str) -> list[str]:
    argv = [binary, "--version"]
    assert_dump_argv(argv)
    return argv


def disc_argv(binary: str, sg_node: str, image_path: str, image_name: str, retries: int = 0) -> list[str]:
    argv = [
        binary,
        "disc",
        f"--drive={sg_node}",
        f"--image-path={image_path}",
        f"--image-name={image_name}",
    ]
    if retries:
        argv.append(f"--retries={retries}")
    assert_dump_argv(argv)
    return argv


def process_start_token(pid: int, reader: Callable[[int], str | None] | None = None) -> str | None:
    if reader is None:
        def reader(current: int) -> str | None:
            try:
                return Path(f"/proc/{current}/stat").read_text(encoding="utf-8")
            except OSError:
                return None
    text = reader(pid)
    if not text:
        return None
    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 2 :].split()
    if len(fields) <= 19:
        return None
    return fields[19]


class HostDump:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self.pid = process.pid
        self.start_token = process_start_token(process.pid) or ""

    def poll(self) -> int | None:
        return self.process.poll()

    def terminate(self) -> None:
        _signal_group(self.pid, signal.SIGTERM)

    def kill(self) -> None:
        _signal_group(self.pid, signal.SIGKILL)


class HostSupervisor:
    """Start Redumper in its own session and copy its output into a bounded log."""

    def spawn(
        self,
        argv: list[str],
        log_path: Path,
        on_exit: Callable[[int, int], None],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> HostDump:
        assert_dump_argv(argv)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("ab", buffering=0)
        pair = open_pty_pair()
        slave: int | None = None
        try:
            if pair is None:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=cwd,
                    env=env,
                    start_new_session=True,
                    close_fds=True,
                )
                output = process.stdout
                if output is None:
                    raise OSError("Redumper output could not be captured.")
                master = output.fileno()
            else:
                master, slave = pair
                process = subprocess.Popen(
                    argv,
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    cwd=cwd,
                    env=env,
                    start_new_session=True,
                    close_fds=True,
                )
        except Exception:
            if pair is not None:
                os.close(pair[0])
                os.close(pair[1])
            log_handle.close()
            raise
        if slave is not None:
            os.close(slave)
        dump = HostDump(process)

        def drain() -> None:
            written = 0
            try:
                while True:
                    if process.poll() is not None and not select.select([master], [], [], 0)[0]:
                        break
                    readable, _, _ = select.select([master], [], [], 0.2)
                    if not readable:
                        continue
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    if written < MAX_LOG_BYTES:
                        take = chunk[: MAX_LOG_BYTES - written]
                        log_handle.write(take)
                        written += len(take)
                code = process.wait()
            finally:
                os.close(master)
                log_handle.close()
            on_exit(process.pid, code)

        threading.Thread(target=drain, name=f"discdeck-dump-{process.pid}", daemon=True).start()
        return dump

    def inspect(self, pid: int, start_token: str) -> str:
        token = process_start_token(pid)
        if token is None:
            return "gone"
        if not start_token or token != start_token:
            return "unknown"
        return "running"


class DumpJobs:
    def __init__(self, service: Any, supervisor: Any | None = None, disk_free: Callable[[Path], int] | None = None) -> None:
        self.service = service
        self.supervisor = supervisor if supervisor is not None else HostSupervisor()
        self.disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._lock = threading.Lock()
        self._live: dict[int, Any] = {}
        self._local_preflight: set[str] = set()
        self.journal_error: str | None = None
        self._jobs: list[dict[str, Any]] = []
        self._load()

    def journal_path(self) -> Path | None:
        raw = self.service.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
        if not raw:
            return None
        return Path(raw) / "state" / "dump-jobs.json"

    def public_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [_public(job) for job in self._jobs]

    def operation_active(self) -> bool:
        with self._lock:
            return any(job["state"] in ACTIVE_STATES for job in self._jobs)

    def reconcile(self, drives: list[dict[str, Any]] | None = None) -> None:
        with self._lock:
            if self.journal_error:
                return
            changed = False
            present = {str(drive["drive_id"]) for drive in drives} if drives is not None else None
            for job in self._jobs:
                if self._observe(job, present):
                    changed = True
            if changed:
                self._store_locked()
            self._sync_leases_locked()

    def start(self, drive_id: str, generation: int, image_name: str, output_root: str) -> dict[str, Any]:
        try:
            name = validate_image_name(image_name)
            root = validate_output_root(output_root)
        except ValueError as exc:
            return self._error("OUTPUT_INVALID", str(exc))
        if self.journal_path() is None:
            return self._error("NOT_READY", "The plugin settings directory is unset, so a dump journal cannot be stored.")
        with self._lock:
            if self.journal_error:
                return self._error("NOT_READY", self.journal_error)
        snapshot = self.service.snapshot()
        module = next((item for item in snapshot["modules"] if item["id"] == "dump.redumper"), None)
        if module is None or not module["enabled"]:
            return self._error("MODULE_DISABLED", "Preservation is disabled. No dump was started.")
        drive = next((item for item in snapshot["drives"] if item["drive_id"] == drive_id), None)
        if drive is None:
            return self._error("DEVICE_LOST", "That drive is not in the current inventory.")
        if int(drive.get("generation") or 0) != int(generation):
            return self._error("STALE_DEVICE", "The drive generation changed. Refresh and choose the drive again.")
        if drive.get("media_present") is not True:
            return self._error("DRIVE_NOT_READY", "This drive has no media in the current snapshot, so no dump was started.")
        sg_node = drive.get("generic_scsi_node")
        if not isinstance(sg_node, str):
            return self._error("SG_NODE_NOT_FOUND", "This drive has no generic SCSI node, so Redumper was not started.")
        access = self.service.access or os.access
        if not access(sg_node, os.R_OK) or not access(sg_node, os.W_OK):
            return self._error("SG_ACCESS_DENIED", f"This user cannot read and write {sg_node}. The plugin was not given root.")
        if drive_id in self.service.physical.leases or self._drive_blocked(drive_id):
            return self._error("DRIVE_BUSY", "This drive already has a DiscDeck operation or an unfinished dump.")
        mount_points = drive.get("mount_points") or []
        owned = self.service.physical.owned_mounts.get(drive_id)
        if mount_points and owned is None:
            return self._error("UNMOUNT_FAILED", "This disc is mounted outside DiscDeck. Unmount it before a dump. That mount was left in place.")
        if owned is not None:
            unmounted = self.service.physical.unmount(drive_id, int(generation))
            if not unmounted["ok"]:
                code = unmounted.get("code") or "UNMOUNT_FAILED"
                if code not in {"PERMISSION_DENIED", "DRIVE_BUSY", "UNMOUNT_FAILED"}:
                    code = "UNMOUNT_FAILED"
                return self._error(code, unmounted.get("message") or "DiscDeck could not unmount this disc before the dump.")
        try:
            free = self.disk_free(root)
        except OSError as exc:
            return self._error("OUTPUT_INVALID", f"The output folder could not be measured. {exc}")
        if free < MIN_FREE_BYTES:
            return self._error("INSUFFICIENT_SPACE", f"The output folder has {free} bytes free. DiscDeck does not know the disc size and will not start below {MIN_FREE_BYTES} bytes.")
        binary = self._binary(snapshot)
        if binary is None:
            return self._error("REDUMPER_MISSING", "The Redumper build shipped with DiscDeck is not available. A system or container copy was not used.")
        described = snapshot["probes"]["redumper"]
        retries = _retries(snapshot)
        iso_destination = root / f"{name}.iso"
        if iso_destination.exists() or iso_destination.is_symlink():
            return self._error(
                "OUTPUT_INVALID",
                f"{name}.iso is already in that folder. Pick another image name or folder. Nothing was overwritten.",
            )
        job_id = "job_" + uuid.uuid4().hex[:12]
        try:
            output_dir = _dumpjob_dir(root)
            output_dir.mkdir()
        except OSError as exc:
            return self._error("OUTPUT_INVALID", f"The dump folder could not be created. {exc}")
        log_path = self._log_path(job_id)
        if log_path is None:
            output_dir.rmdir()
            return self._error("NOT_READY", "No log directory is available for the dump.")
        job = _new_job(job_id, drive, name, output_dir, binary, described.get("launch_kind"), log_path)
        with self._lock:
            self.service.physical.leases[drive_id] = "dump"
            self._local_preflight.add(job_id)
            self._jobs.append(job)
            self._store_locked()
        env, cwd = _host_launch(self.service.environ, getattr(self.service, "home", None))
        version = self.service.dump_runner(version_argv(binary), timeout=30, env=env, cwd=cwd, pty=True)
        version_line = _first_line(version.stdout) or _first_line(version.stderr)
        if version.code != 0 or not version_line:
            detail = version_line or "no output"
            notice = f"redumper --version exited {version.code}: {detail}. The disc command was not started."
            self._finish_preflight(job_id, "failed", "REDUMPER_VERSION_FAILED", notice)
            return self._error("UNSUPPORTED_REDUMPER_VERSION", notice)
        try:
            argv = disc_argv(binary, sg_node, str(output_dir), name, retries)
        except Exception as exc:  # noqa: BLE001 - policy refusal becomes a job failure
            self._finish_preflight(job_id, "failed", "OUTPUT_INVALID", str(exc))
            return self._error("OUTPUT_INVALID", str(exc))
        try:
            handle = self.supervisor.spawn(argv, log_path, self._on_exit, cwd=cwd, env=env)
        except Exception as exc:  # noqa: BLE001
            self._finish_preflight(job_id, "failed", "REDUMPER_MISSING", f"Redumper could not be started. {exc}")
            return self._error("REDUMPER_MISSING", f"Redumper could not be started. {exc}")
        with self._lock:
            current = self._find_locked(job_id)
            if current is None:
                return self._error("INTERNAL_ERROR", "The dump journal lost the new job.")
            current["state"] = "running"
            current["version_line"] = version_line[:200]
            current["argv"] = argv
            current["command_fingerprint"] = hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()
            current["pid"] = handle.pid
            current["process_start"] = handle.start_token
            current["message"] = "Redumper is running. Progress is indeterminate, and a finished process is not a verified dump."
            current["launch_kind"] = described.get("launch_kind")
            self._live[handle.pid] = handle
            self._local_preflight.discard(job_id)
            self._touch_locked(current)
            self._store_locked()
            public = _public(current)
        return self._ok({"action": "start_dump", **public})

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._find_locked(job_id)
            if job is None:
                return self._error("NOT_READY", "That dump is not in the journal.")
            if job["state"] not in {"running", "orphaned_running"}:
                return self._error("NOT_READY", "That dump is not running.")
            self._signal_locked(job, "terminate")
            job["state"] = "cancel_requested"
            job["message"] = "Cancel was requested. The output folder was kept."
            self._touch_locked(job)
            self._store_locked()
        self.reconcile()
        with self._lock:
            public = _public(self._find_locked(job_id) or job)
        return self._ok({"action": "cancel_dump", **public})

    def force_stop(self, job_id: str, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            return self._error("CONSENT_REQUIRED", "Force stop needs a second confirmation. The process was not killed.")
        with self._lock:
            job = self._find_locked(job_id)
            if job is None:
                return self._error("NOT_READY", "That dump is not in the journal.")
            if job["state"] != "cancel_requested":
                return self._error("NOT_READY", "Request cancel before a force stop.")
            self._signal_locked(job, "kill")
            job["message"] = "Force stop was sent. The output folder was kept and was not verified."
            self._touch_locked(job)
            self._store_locked()
        self.reconcile()
        with self._lock:
            public = _public(self._find_locked(job_id) or job)
        return self._ok({"action": "force_stop_dump", **public})

    def acknowledge(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._find_locked(job_id)
            if job is None:
                return self._error("NOT_READY", "That dump is not in the journal.")
            if not job.get("needs_ack"):
                return self._error("NOT_READY", "That dump is not waiting for a safety acknowledgement.")
            status, _code = self._process_status_locked(job)
            if status == "running":
                return self._error("DRIVE_BUSY", "The dump process is still running. DiscDeck will not start another dump on this drive.")
            job["state"] = "interrupted"
            job["needs_ack"] = False
            job["verification"] = "unverified"
            job["message"] = "DiscDeck is no longer treating this drive as busy. The output was kept and was not verified."
            self._touch_locked(job)
            self._store_locked()
            self._sync_leases_locked()
            public = _public(job)
        return self._ok({"action": "acknowledge_dump", **public})

    def _on_exit(self, pid: int, code: int) -> None:
        with self._lock:
            job = next((item for item in self._jobs if item.get("pid") == pid and item["state"] in {"running", "cancel_requested", "preflight"}), None)
            if job is None:
                return
            self._apply_exit_locked(job, code)
            self._store_locked()
            self._sync_leases_locked()

    def _finish_preflight(self, job_id: str, state: str, code: str, message: str) -> None:
        del code
        with self._lock:
            job = self._find_locked(job_id)
            if job is None:
                return
            job["state"] = state
            job["message"] = message
            job["verification"] = "unverified"
            job["needs_ack"] = False
            self._local_preflight.discard(job_id)
            self._touch_locked(job)
            self._store_locked()
            self._sync_leases_locked()
            _remove_empty_dumpjob(job)

    def _observe(self, job: dict[str, Any], present: set[str] | None) -> bool:
        if job["state"] not in ACTIVE_STATES and not job.get("needs_ack"):
            return False
        if job["state"] == "preflight" and job["job_id"] not in self._local_preflight:
            job["state"] = "failed"
            job["needs_ack"] = False
            job["verification"] = "unverified"
            job["message"] = "The dump stopped during preflight before Redumper started. The output folder was kept."
            self._touch_locked(job)
            return True
        changed = False
        if present is not None and job["state"] in {"running", "cancel_requested", "orphaned_running"} and job["drive_id"] not in present:
            self._signal_locked(job, "terminate")
            job["state"] = "interrupted"
            job["needs_ack"] = False
            job["verification"] = "unverified"
            job["message"] = "The drive disappeared. The dump was stopped. Output was kept and was not verified."
            self._touch_locked(job)
            return True
        if job["state"] not in ACTIVE_STATES:
            return False
        status, code = self._process_status_locked(job)
        if status == "running":
            if job["state"] == "running" and job.get("pid") not in self._live:
                job["state"] = "orphaned_running"
                job["needs_ack"] = True
                job["message"] = "DiscDeck restarted while Redumper was still running. The log was not reattached, and the result is not verified."
                self._touch_locked(job)
                changed = True
            return changed
        if job["state"] == "preflight":
            return changed
        if status == "unknown":
            if job["state"] != "orphaned_running":
                job["state"] = "orphaned_running"
                job["needs_ack"] = True
                job["message"] = "DiscDeck cannot confirm that this process is the recorded dump. The drive stays busy until you confirm it is safe."
                self._touch_locked(job)
                changed = True
            return changed
        watched = job.get("pid") in self._live
        if code is None:
            job["state"] = "interrupted"
            job["needs_ack"] = True
            job["verification"] = "unverified"
            job["message"] = "The dump process ended while DiscDeck was not watching. The output was kept and was not verified."
        else:
            self._apply_exit_locked(job, code, watched=watched)
        self._touch_locked(job)
        return True

    def _apply_exit_locked(self, job: dict[str, Any], code: int, watched: bool = True) -> None:
        job["exit_code"] = code
        job["verification"] = "unverified"
        job["needs_ack"] = False if watched else True
        folder = Path(str(job.get("output_dir") or "")).name or "the dump folder"
        if job["state"] == "cancel_requested" or code < 0:
            job["state"] = "interrupted"
            job["message"] = f"The dump stopped before it finished. The files stayed in {folder} and were not verified."
            return
        if code == 0:
            job["state"] = "completed_warnings"
            moved = _move_finished_iso(job)
            image = job.get("image_name") or "image"
            if moved == "moved":
                job["message"] = (
                    f"{image}.iso was moved into the folder you chose. Logs and the other files stayed in {folder}. "
                    "DiscDeck did not verify the files."
                )
            elif moved == "exists":
                job["message"] = (
                    f"{image}.iso is already in the folder you chose, so it was not replaced. "
                    f"The new files stayed in {folder}."
                )
            elif moved == "missing":
                job["message"] = (
                    f"Redumper exited 0 and did not write {image}.iso. The other files stayed in {folder}. "
                    "DiscDeck did not verify the files."
                )
            else:
                job["message"] = f"Redumper exited 0. {image}.iso could not be moved. The files stayed in {folder}."
            return
        job["state"] = "failed"
        job["message"] = f"Redumper exited {code}. The files stayed in {folder} and were not verified."

    def _process_status_locked(self, job: dict[str, Any]) -> tuple[str, int | None]:
        pid = job.get("pid")
        if not isinstance(pid, int):
            return "exited", None
        handle = self._live.get(pid)
        if handle is not None:
            code = handle.poll()
            if code is None:
                return "running", None
            return "exited", code
        status = self.supervisor.inspect(pid, str(job.get("process_start") or ""))
        if status == "running":
            return "running", None
        if status == "unknown":
            return "unknown", None
        return "exited", None

    def _signal_locked(self, job: dict[str, Any], kind: str) -> None:
        pid = job.get("pid")
        if not isinstance(pid, int):
            return
        handle = self._live.get(pid)
        if handle is not None:
            if kind == "kill":
                handle.kill()
            else:
                handle.terminate()
            return
        if kind == "kill":
            _signal_group(pid, signal.SIGKILL)
        else:
            _signal_group(pid, signal.SIGTERM)

    def _drive_blocked(self, drive_id: str) -> bool:
        with self._lock:
            return any(job["drive_id"] == drive_id and (job["state"] in ACTIVE_STATES or job.get("needs_ack")) for job in self._jobs)

    def _binary(self, snapshot: dict[str, Any]) -> str | None:
        probe = snapshot["probes"]["redumper"]
        path = probe.get("path")
        if probe.get("launch_kind") != "native_executable" or probe.get("origin") not in {"bundled", "updated"}:
            return None
        if isinstance(path, str) and path.startswith("/") and Path(path).is_file() and not Path(path).is_symlink():
            return path
        return None

    def _log_path(self, job_id: str) -> Path | None:
        raw = self.service.environ.get("DECKY_PLUGIN_LOG_DIR")
        if raw:
            return Path(raw) / "dumps" / f"{job_id}.log"
        journal = self.journal_path()
        if journal is None:
            return None
        return journal.parent / "dump-logs" / f"{job_id}.log"

    def _find_locked(self, job_id: str) -> dict[str, Any] | None:
        return next((job for job in self._jobs if job["job_id"] == job_id), None)

    def _touch_locked(self, job: dict[str, Any]) -> None:
        job["updated_at"] = _now()

    def _sync_leases_locked(self) -> None:
        blocked = {job["drive_id"] for job in self._jobs if job["state"] in ACTIVE_STATES or job.get("needs_ack")}
        leases = self.service.physical.leases
        for drive_id, reason in list(leases.items()):
            if reason == "dump" and drive_id not in blocked:
                leases.pop(drive_id, None)
        for drive_id in blocked:
            if drive_id not in leases:
                leases[drive_id] = "dump"

    def _load(self) -> None:
        path = self.journal_path()
        if path is None or not path.is_file():
            self._jobs = []
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.journal_error = "The dump journal could not be read. It was not replaced."
            return
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("jobs"), list):
            self.journal_error = "The dump journal has an unknown shape. It was not replaced."
            return
        jobs: list[dict[str, Any]] = []
        for item in payload["jobs"]:
            if not isinstance(item, dict) or not isinstance(item.get("job_id"), str):
                self.journal_error = "The dump journal has an unknown shape. It was not replaced."
                self._jobs = []
                return
            jobs.append(item)
        self._jobs = jobs

    def _store_locked(self) -> None:
        path = self.journal_path()
        if path is None:
            raise OSError("The plugin settings directory is not set.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "jobs": self._jobs}, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _ok(self, result: dict[str, Any]) -> dict[str, Any]:
        self.service.revision += 1
        result["hardware_validated"] = False
        result["verification"] = result.get("verification") or "unverified"
        return envelope_ok(result, self.service.revision, self.service.epoch)

    def _error(self, code: str, message: str) -> dict[str, Any]:
        self.service.revision += 1
        return envelope_error(code, message, retryable=code in {"DRIVE_BUSY", "NOT_READY", "INSUFFICIENT_SPACE"}, revision=self.service.revision, epoch=self.service.epoch)


def _retries(snapshot: dict[str, Any]) -> int:
    value = snapshot.get("settings", {}).get("settings", {}).get("redumper_retries", 0)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 5:
        return value
    return 0


def _dumpjob_dir(root: Path, moment: datetime | None = None) -> Path:
    stamp = (moment or datetime.now().astimezone()).strftime("%Y-%m-%d_%H%M%S")
    candidate = root / f"dumpjob_{stamp}"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 1000):
        candidate = root / f"dumpjob_{stamp}_{suffix}"
        if not candidate.exists():
            return candidate
    raise OSError("A dump folder name could not be chosen.")


def _move_finished_iso(job: dict[str, Any]) -> str:
    """Move the finished ISO into the chosen folder. Logs and other files stay in the dumpjob folder."""
    staging = Path(str(job.get("output_dir") or ""))
    image_name = job.get("image_name")
    if not isinstance(image_name, str) or _DUMPJOB_DIR.fullmatch(staging.name) is None:
        return "failed"
    source = staging / f"{image_name}.iso"
    destination = staging.parent / source.name
    if destination == source or not source.is_file() or source.is_symlink():
        return "missing" if destination != source else "failed"
    if destination.exists() or destination.is_symlink():
        return "exists"
    try:
        os.link(source, destination)
    except FileExistsError:
        return "exists"
    except OSError:
        if destination.exists() or destination.is_symlink():
            return "exists"
        try:
            os.replace(source, destination)
        except OSError:
            return "failed"
        job["iso_path"] = str(destination)
        return "moved"
    try:
        source.unlink()
    except OSError:
        destination.unlink(missing_ok=True)
        return "failed"
    job["iso_path"] = str(destination)
    return "moved"


def _remove_empty_dumpjob(job: dict[str, Any]) -> None:
    path = Path(str(job.get("output_dir") or ""))
    if _DUMPJOB_DIR.fullmatch(path.name) is None:
        return
    try:
        path.rmdir()
    except OSError:
        return


def _new_job(
    job_id: str,
    drive: dict[str, Any],
    image_name: str,
    output_dir: Path,
    binary: str,
    launch_kind: Any,
    log_path: Path,
) -> dict[str, Any]:
    now = _now()
    return {
        "job_id": job_id,
        "state": "preflight",
        "drive_id": drive["drive_id"],
        "generation": drive.get("generation"),
        "block_node": drive.get("block_node"),
        "generic_scsi_node": drive.get("generic_scsi_node"),
        "scsi_address": drive.get("scsi_address"),
        "sysfs_device": drive.get("sysfs_device"),
        "image_name": image_name,
        "output_dir": str(output_dir),
        "binary": binary,
        "launch_kind": launch_kind,
        "version_line": None,
        "argv": None,
        "command_fingerprint": None,
        "pid": None,
        "process_start": None,
        "log_path": str(log_path),
        "exit_code": None,
        "verification": "unverified",
        "needs_ack": False,
        "message": "Checking Redumper before the disc command.",
        "created_at": now,
        "updated_at": now,
        "hardware_validated": False,
    }


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "state": job["state"],
        "drive_id": job["drive_id"],
        "block_node": job.get("block_node"),
        "generic_scsi_node": job.get("generic_scsi_node"),
        "image_name": job.get("image_name"),
        "output_dir": job.get("output_dir"),
        "iso_path": job.get("iso_path"),
        "verification": "unverified",
        "message": job.get("message"),
        "exit_code": job.get("exit_code"),
        "launch_kind": job.get("launch_kind"),
        "needs_ack": bool(job.get("needs_ack")),
        "log_path": job.get("log_path"),
        "hardware_validated": False,
    }


def _signal_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except (PermissionError, OSError):
        try:
            os.kill(pid, sig)
        except OSError:
            return


def _host_launch(environ: dict[str, str], home: Path | None) -> tuple[dict[str, str], str | None]:
    """Give the managed Redumper a normal home directory. The executable is never taken from PATH."""
    merged = dict(os.environ)
    for key, value in environ.items():
        if isinstance(value, str):
            merged[key] = value
    paths: list[str] = []
    for item in ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"):
        if item not in paths:
            paths.append(item)
    for item in (merged.get("PATH") or "").split(os.pathsep):
        if item and item not in paths:
            paths.append(item)
    merged["PATH"] = os.pathsep.join(paths)
    cwd = _existing_directory(home)
    if cwd is None and merged.get("HOME"):
        cwd = _existing_directory(Path(merged["HOME"]))
    if cwd is not None:
        merged["HOME"] = cwd
    if not merged.get("XDG_RUNTIME_DIR"):
        runtime = Path(f"/run/user/{os.geteuid()}")
        if runtime.is_dir():
            merged["XDG_RUNTIME_DIR"] = str(runtime)
    return merged, cwd


def _existing_directory(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if resolved.is_dir():
        return str(resolved)
    return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return ""


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
