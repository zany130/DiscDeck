# Host compatibility matrix

Target under investigation: Bazzite x86_64, Steam Gaming Mode, locally connected optical hardware. The secondary SteamOS target is not in this matrix.

This table separates the 2026-11-09 passive inventory from operations Phase 0 has not run. Inventory is not a pass. Cloud fixtures imitate the inventory so regressions are visible without hardware; a passing fixture is not a host pass.

| Area | Host inventory | Phase 0 plugin behavior | Gate |
|---|---|---|---|
| OS | Bazzite 45.20261104, kernel `7.2.15-ogc1.1.fc45.x86_64`, Secure Boot on | Reports the kernel only if a future probe reads it. Phase 0 does not change boot settings | Not a DiscDeck gate |
| Decky loader | File present, version marker `v3.3.1`, service `User=root`, service was inactive | Reads effective UID and `DECKY_*` constants. Does not request `root`. Does not start the service | P0-A BLOCKED |
| Plugin identity | Not measured. The root service unit does not prove the plugin UID | Compares owner and effective IDs. Drops unexpected UID 0 only when `DECKY_USER` resolves to a non-root account. Never assumes UID 1000 | P0-A BLOCKED |
| Plugin directories | Not measured | Reports existence and writability. Durability is `untested` | P0-A BLOCKED |
| Optical nodes | `sr0→sg1` on USB `13fd:5912`; `sr1→sg2` LUN 0 and `sr2→sg3` LUN 1 on shared JMicron `152d:2338` | Maps `scsi_generic` links. Ignores unrelated `sg0`. Identity follows the sysfs device, not the `sr` number | P0-B BLOCKED |
| Media | Snapshot had no media. `MediaAvailable=false`. `Optical=false` did not match sysfs type 5 | Keeps those drives optical. Does not mount, eject, or close the tray | P0-B BLOCKED |
| UDisks2 | Service active and readable by the host user. Build `a634c8e` reported `UNSUPPORTED` for the systemd 257 object-map reply | Read-only `GetManagedObjects` only when the bus name already has a PID. Accepts pair and object JSON. Does not activate a stopped service | P0-B / P0-F BLOCKED |
| Permissions | Named user ACL `rw-` on optical nodes and `vhba_ctl`. `sg0` denied to the host user | Reports this process's `access` and named ACL. A denial stays on the dump module | P0-C BLOCKED |
| SG_IO | Not performed | Not performed | P0-C BLOCKED |
| Redumper | Wrapper in the user bin; container package `772-1`; binary not launched. Build `a634c8e` reported `REDUMPER_MISSING` because Decky's PATH omitted that directory | Searches PATH, then `$DECKY_USER_HOME/.local/bin` or `$HOME/.local/bin`, then an absolute configured path. Does not execute a wrapper. Does not run `disc` | P0-D BLOCKED |
| VHBA | Module loaded, version `20260313`, signed, control node ACL present | Checks `/sys/module/vhba` and the control node. Does not `modprobe` | P0-E BLOCKED |
| CDEmu | Client and daemon 3.3.1 installed. User service inactive and activatable. Bus name had no owner | Reports `DAEMON_INACTIVE`. Does not call `cdemu status` or load an image | P0-E BLOCKED |
| ISO loop | Not tested. UDisks2 was present | Does not call `LoopSetup` | P0-F BLOCKED |
| Steam / Proton | Native Steam and several Proton tool directories | Lists tool directory names. Does not read shortcuts or prefixes and does not launch | P0-G BLOCKED |
| Launcher policy | Not configured | Experimental launch and autoplay stay off unless a valid settings file says otherwise. They still cannot become `active` while untested | P0-G / P0-H BLOCKED |
| Recovery | No DiscDeck process existed | Unload does not eject or delete user data. Restart behavior is untested | P0-H BLOCKED |

## Affected modules while gates stay blocked

| Module | Default enabled | Capability while unproven | What still works in the diagnostic UI |
|---|---|---|---|
| `physical` | Always | `untested` when inventory is visible, otherwise `missing` or `denied` | Lists observed drives and states that operations were not run |
| `images.iso` | Yes | `untested` or `missing` | States that loop setup was not run |
| `dump.redumper` | Yes | `missing`, `denied`, or `untested` | Shows discovery and version policy. No dump |
| `virtual.cdemu` | Yes | `untested` when installed but inactive; `missing` when absent | Shows VHBA and daemon state. No load |
| `resources.pcgamingwiki` | Yes | `untested` | No network request |
| `launch.experimental` | No | `disabled` | No launch control |
| `launch.autoplay` | No | `disabled` | No autoplay |

An enabled flag cannot turn any of these modules `active` in Phase 0. The backend rejects `capability: ready`.
