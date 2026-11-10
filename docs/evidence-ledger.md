# Evidence ledger

Phase 0 records what was read, what was mocked, and what remains unproven. A row is not PASS unless the required observation happened on the target host. None of the P0 gates are PASS.

Labels:

- **Upstream:** the interface was read from a pinned source. That does not mean it was executed on Bazzite.
- **Host inventory:** a passive observation supplied in the 2026-11-09 host report. It was not repeated by this cloud environment.
- **Cloud mock:** a unit test with a fixture or scripted command runner.
- **Untested:** the operation was not performed.

The implementation specification hash is `29d03553468afc61b0e25029ca9ecfc89175682f8151e8fa2b67dc832c0166bb`. It was not modified.

## Pinned sources

| Source | Pin | How it was checked |
|---|---|---|
| decky-plugin-template | `90d0780e882a17f5714fc6de044c645f22608290` (2026-04-10) | Local tree matched that commit before DiscDeck edits |
| Decky Loader | tag `v3.3.1`, commit `ffd103b9c1a4ce5bf305e7c0998eda6e05457dad` | `decky.pyi`, `plugin.py`, and `sandboxed_plugin.py` were read |
| `@decky/api` | 1.1.3, gitHead `d1b7f16070777a0ada939cbacd3606eeba0574f5` | Public exports listed in `tests/fixtures/decky-api-1.1.3-exports.json` |
| `@decky/ui` | 4.11.0, gitHead `fd651eb989a723491857af13be1df383d80a4130` | `ButtonItem`, `PanelSection`, `PanelSectionRow`, and `staticClasses` used from public declarations |
| `@decky/rollup` | 1.0.2 | Frontend build entry |
| Decky CLI | tag 0.0.8 `src/cli/plugin/build.rs` | ZIP layout copied; CLI binary not run |
| pnpm | 9.15.9 | Lockfile version 9.0 |

The template `decky.pyi` and loader v3.3.1 `decky.pyi` differ only in the `emit` docstring. The constants and migration helpers match. DiscDeck uses the documented constants and does not import loader-private modules.

## Decky contract checked in source

| Contract | Evidence | Limit |
|---|---|---|
| `callable` / method arguments | Loader `execute_method` passes positional `*args` for `api_version` > 0. `plugin.json` keeps `api_version` 1 | Not executed inside Decky |
| `decky.emit` | Sandbox replaces `emit` and writes a socket event. Frontend `addEventListener` / `removeEventListener` are public exports | Round trip not observed on a Deck |
| Lifecycle | `_main`, `_unload`, `_uninstall` are optional and awaited. `_migration` runs only if defined | DiscDeck defines no `_migration`, so template example paths are not moved |
| Directories | Settings, runtime, and logs are `$DECKY_HOME/settings|data|logs/<plugin directory>` | Durability across restarts is untested. No fallback directory was created |
| Identity | `DECKY_USER` is the installation owner. `USER` / `HOME` follow the effective user. `root` in `flags` selects the effective (usually root) account | DiscDeck's flags are `["debug"]` only. The exact flag `root` is absent |
| `debug` | Loader reloads a plugin that is already loaded when `debug` is present | Not a privilege flag |
| Python path | Loader appends `<plugin>/py_modules` | This is why diagnostics live in `py_modules/discdeck` rather than the template's `backend/` tree |
| File picker, toaster, `useQuickAccessVisible` | Exported by `@decky/api` 1.1.3 | Toaster and visibility are used. The file picker is not used in Phase 0 |
| Private loader globals | Present in the API package as an internal connection | DiscDeck does not reference them |

`skipLibCheck` is enabled because the pinned `@decky/api` declarations import `react-router` types that are not installed. That is a toolchain gap, not a new API.

## Host inventory (not re-run)

The cloud agent has no access to the gaming PC. These points are copied from the passive host report and redacted. They are not Phase 0 passes.

| Observation | Status |
|---|---|
| Bazzite 45.20261104, kernel `7.2.15-ogc1.1.fc45.x86_64`, Secure Boot enabled | Host inventory |
| Host account UID/GID 1000, not a member of `cdrom` or `disk`; optical access described as named ACLs | Host inventory |
| PluginLoader file exists; `.loader.version` contains `v3.3.1`; `plugin_loader.service` is `User=root` and was inactive | Host inventory. Service user is not the plugin UID |
| Three optical nodes at that snapshot: `sr0→sg1` (`13fd:5912`), `sr1→sg2` and `sr2→sg3` sharing JMicron `152d:2338` at LUNs 0 and 1 | Host inventory. Node numbers are ephemeral |
| `/dev/sg0` existed and was not an optical mapping | Host inventory |
| Named `user:<host user>:rw-` ACL on the optical nodes and `/dev/vhba_ctl`; `sg0` not accessible | Host inventory. Not an SG_IO test |
| UDisks2 active; three drives readable; `MediaAvailable=false`; `Optical=false` while sysfs type was 5 | Host inventory. No mount |
| Redumper on `PATH` is a distrobox-export wrapper into container `arch`, package `redumper 772-1` | Host inventory. `--version` was not run |
| `cdemu` 3.3.1-1.fc45, VHBA module loaded and signed, user daemon inactive but activatable | Host inventory. Daemon was not started |
| Native Steam RPM and Proton tool directories present | Host inventory. No shortcut or prefix was read |

Personal home paths and the account name are omitted here. USB identifiers and drive model strings are hardware facts from that snapshot.

## Cloud mocks

| Check | Result here |
|---|---|
| Shared-bridge fixture keeps distinct LUNs and ignores unlinked `sg0` | Mock passed |
| Renaming `sr2` to `sr9` keeps the drive id derived from the sysfs device | Mock passed |
| `Drive.Optical=false` does not hide an `sr` node | Mock passed |
| Inactive UDisks2 and inactive CDEmu are not activated | Mock passed |
| Installed inactive CDEmu is `untested` / `DAEMON_INACTIVE`, not missing and not ready | Mock passed |
| Distrobox wrapper is identified and not executed | Mock passed |
| Native `--version` is allowed only as `["redumper", "--version"]` and still leaves the module untested | Mock passed |
| SG access denial is `SG_ACCESS_DENIED` and does not request root | Mock passed |
| Missing binary, bus client, or sysfs class is `missing` | Mock passed |
| Steam discovery does not open `shortcuts.vdf` or a Proton prefix | Mock passed |
| Invalid settings are not rewritten; launcher and autoplay default off | Mock passed |
| Unexpected UID 0 drops only to a resolved non-root `DECKY_USER` | Mock passed. Not executed as root |
| Snapshot capability is never `ready` and `hardware_validated` is false | Mock passed |
| ZIP layout, absent `root` flag, and publish pointer order | Mock passed |

## Live Decky session

Observed on the gaming PC after installing build `a634c8e`, with the plugin running inside Decky Loader v3.3.1. Personal home paths are omitted. This is a host observation. It does not move a gate to PASS.

| Check | Observation |
|---|---|
| Identity | Effective user matched the owner. UID 1000, GID 1000. Root flag no. Loader `v3.3.1`. Hardware validated no |
| Events | Probe toasts reported revisions 24, then 25, then 26 |
| Drives | `sr0→sg1` Generic External SCSI `6:0:0:0`; `sr1→sg2` TSSTcorp SH-D163B SCSI `7:0:0:0` shared bridge; `sr2→sg3` PLEXTOR PX-W4012A SCSI `7:0:0:1` shared bridge. Operations not run. `sg0` was not listed |
| CDEmu | `DAEMON_INACTIVE`, active no, VHBA loaded yes |
| Steam | `untested`, 21 tool directories, shortcuts read no |
| Redumper | `REDUMPER_MISSING` in the Decky process. The wrapper is installed under the user bin, which that process PATH did not include |
| UDisks2 | Service was active. The reply was `UNSUPPORTED` because this build only accepted the older array-of-pairs JSON |

Build `a338878` was installed from the development URL and refreshed on the same machine. UDisks2 read as `observed`. All three drives reported `no media`, kept the same `sr`/`sg` mapping and shared-bridge lines, and still said operations were not run. Redumper read as `distrobox_wrapper`, version `not_executed`, executed no. CDEmu stayed `DAEMON_INACTIVE` with VHBA loaded, and Steam still listed 21 tool directories without reading shortcuts. The wrapper was not executed.

## Eject log from build 4574acb

The attached plugin log `2026-11-09 22.19.10` contains only the startup line. Mount and unmount returned the expected `NOT_READY` results. Eject reached UDisks2 and failed, but that failure was not written to the plugin log. UDisks2 `Drive.Eject` authorizes through polkit and then runs the `eject` command. The plugin process is outside the login session, so that authorization can fail. The next build logs the UDisks2 result and, only after that denial, runs `eject` on the matching `/dev/srN` as the current user when that node is writable. It does not use root and does not close trays.

## Phase 1 action feedback

Build `c80709b` toasted `physical revision` plus a counter for mount, unmount, and eject. That toast came from the change event, and the following refresh cleared the real result, so a refused eject looked like a silent no-op. The next build keeps the UDisks2 code and message on screen. A direct `NotAuthorized` retries the same `Drive.Eject` inside the user session. It still does not use an ioctl, and no host tray has been recorded as opened.

## Phase 1 physical actions

Mount, unmount, and confirmed eject are implemented. Mount uses the read-only option. Tray close returns `TRAY_CLOSE_UNSUPPORTED` and does not issue a close command. On 2026-11-10 the gaming PC reported that empty-drive mount and unmount returned `NOT_READY`, and that eject opened the tray as expected. A filesystem mount, an unmount of a DiscDeck mount, an audio disc, and an unplug/replug were not run, so P0-B stays blocked and `hardware_validated` stays false.

## Gate ledger

| Gate | Status | Why it is not PASS |
|---|---|---|
| P0-A Decky runtime | BLOCKED | Identity and probe events 24–26 were observed on build `a634c8e`. Logger files, listener cleanup, and directory durability were not checked |
| P0-B Physical drives | BLOCKED | Inventory, empty-drive `NOT_READY` mount/unmount, and a successful eject were observed. A data-disc mount, DiscDeck unmount, audio/mixed media, and unplug/replug were not run. Tray close is intentionally unsupported |
| P0-C Permissions | BLOCKED | ACL fixtures and denial tests exist. Plugin-process SG_IO and polkit were not run |
| P0-D Redumper | BLOCKED | Build `a338878` found the distrobox wrapper and did not execute it. No disc was dumped |
| P0-E CDEmu / VHBA | BLOCKED | Presence checks exist. No interface handshake or image load was performed, and the daemon was not started |
| P0-F ISO loop | BLOCKED | `LoopSetup` is not called |
| P0-G Steam / Proton | BLOCKED | The live panel listed 21 tool directories and did not read shortcuts. No launch or prefix inspection was performed |
| P0-H Recovery | BLOCKED | No Decky reload, backend restart, or interrupted job exists |

## Decisions left inside the written fallback

- No `root` flag and no privileged helper.
- No automatic `modprobe`, service start, mount, eject, dump, or Steam edit.
- Runtime durability is reported as `untested`. The specified fallback, a `state/` directory under the settings dir, is not created until a restart test shows it is needed.
- Redumper version is not read when the file is a distrobox wrapper.
- CDEmu methods are not called while the daemon is inactive.
- `Optical=false` does not override sysfs type 5 or an `sr` node name.
