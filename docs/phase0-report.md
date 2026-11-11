# Phase 0 report

DiscDeck Phase 0 is a diagnostic Decky plugin and the CI that packages it. It is not a physical disc manager. Production mount, eject, dump, virtual-disc, and launch code was not added.

## What was built

- Repository metadata for DiscDeck, without a `root` plugin flag.
- Read-only Python probes for Decky identity, UDisks2, sysfs `sr`/`sg` mapping, permissions, Redumper, CDEmu/VHBA, and Steam tool discovery.
- A Quick Access panel that refreshes those probes, emits `discdeck:changed`, and removes that listener on dismount.
- Unit fixtures for the shared two-LUN bridge, named ACLs, an installed but inactive CDEmu service, and a distrobox Redumper wrapper.
- A ZIP packager that follows Decky CLI 0.0.8's layout, a verifier, and GitHub Actions that upload `DiscDeck-phase0-dev-<full-sha>` after the checks pass.
- A development publish path. GitHub Releases work for this public repository without new credentials. Cloudflare R2 is implemented and waits for secrets and a confirmed hostname.

## Local verification in this workspace

Commands that completed while preparing the branch:

- `pnpm run typecheck`
- `pnpm run lint`
- `pnpm test` — 8 frontend tests
- `PYTHONPATH=py_modules:. python3 -m unittest discover -s tests -t .` — 45 tests
- `node --test distribution/worker.test.mjs` — 2 tests
- `pnpm run build`
- `python3 scripts/package_plugin.py` and `scripts/verify_zip.py`

The Python suite covers runtime identity, device identity, UDisks2, permissions, Redumper, CDEmu, Steam, capability policy, RPC cleanup, packaging, and the rule that untested hardware is not `ready`. Re-run the suite on the commit that is reviewed; do not treat this note as a later CI result.

## ZIP location

GitHub Actions uploads the artifact from the **Validate and package** job. The artifact name is `DiscDeck-phase0-dev-<full commit sha>`. The file inside it is `DiscDeck-phase0-dev-<7-character sha>.zip`.

After the publish job succeeds on an allowlisted branch, the same bytes are also the development install URL documented in [distribution.md](distribution.md). That job has not been observed yet at the time this report was written. The URL is not live merely because the workflow file exists.

## Security

- `plugin.json` flags are `debug` only. The loader's privilege flag is the exact string `root`, and it is not set.
- If the process is unexpectedly UID 0, it drops to the resolved `DECKY_USER` account or reports `PRIVILEGE_DROP_UNVERIFIED`. It does not guess UID 1000.
- Command arguments are allowlisted. Mount, eject, `modprobe`, service start, `cdemu`, `steam`, and `redumper disc` are refused.
- UDisks2 and CDEmu are not activated when their bus names have no owner.
- Redumper wrappers are not executed. A native `--version` probe exists but is not the default, and it still does not mark dumping ready.
- Settings reads do not rewrite a missing or invalid file. Launcher and autoplay default off.
- Unload and uninstall do not eject media or delete user files.
- Published metadata stores the commit and `hardware_validated: false`. It does not store host paths or secrets.
- No kernel module, udev rule, polkit rule, Secure Boot setting, Steam shortcut, or Proton prefix is changed.

## Install and look at diagnostics on Bazzite

Do this in a window when you are willing to install a Decky plugin. The plugin does not start CDEmu, dump a disc, or touch Steam data.

1. Download the Actions artifact `DiscDeck-phase0-dev-<sha>`, or use the development URL after the publish job has succeeded.
2. On the gaming PC, enable Decky **Developer mode**.
3. Open **Settings → Developer → Third-Party Plugins**.
4. Choose **Install Plugin from ZIP File** or **Install Plugin from URL**.
5. Accept Decky's third-party warning. This build has not been hardware-validated.
6. Open the DiscDeck Quick Access menu.
7. Use **Refresh diagnostics** and **Send probe event**. **Check Redumper version policy** must report that a wrapper was not executed.
8. Confirm the panel shows the effective UID, that the root flag is no, and that every module is `untested`, `missing`, `denied`, or `disabled` rather than a passed hardware gate.
9. Copy the on-screen reason codes into the evidence ledger if you want a host run recorded. Do not mark P0-A or P0-B PASS from the cloud tests.

Optional later, and only with an explicit decision to run them: `redumper --version` for the wrapper, a CDEmu handshake, a read-only mount, and an SG_IO probe. Those are still outside this ZIP's automatic behavior.

## Known limitations

- Live Decky RPC, event delivery, logger files, and directory durability are untested on the machine.
- The cloud environment cannot see the optical drives, so every hardware line in CI is a mock.
- `GetManagedObjects` is skipped when UDisks2 is not already active, so a stopped service stays untested instead of being started.
- Build `a634c8e` rejected the systemd 257 UDisks2 object map and did not search the XDG user bin for Redumper. Build `a338878` was rerun on the gaming PC: UDisks2 read as `observed` with no media, and Redumper read as an unexecuted distrobox wrapper.
- Tray close, media-change signals, and renumber-after-unplug are not implemented.
- The GitHub canonical asset replacement has a short window if an upload fails after the previous asset is removed. R2 pointer publication avoids that and is not deployed.
- The custom hostname is intentionally unset.
- `.vscode/defsettings.json` still has the template's `/home/deck` deploy example. The plugin does not use it.

## Stop line

Phase 1 adds explicit read-only mount, DiscDeck-owned unmount, and confirmed eject. On 2026-11-10 the user reported the six physical checks passed, including a data-disc mount, an audio-disc refusal, and an unplug/replug. The mount path and `sr` numbers were not recorded. Phase 2 can request a read-only ISO loop after a file is picked. That loop is not a virtual disc, CDEmu is not used, and no host ISO mount has been observed. Redumper jobs, CDEmu loads, and the launcher are not started.
