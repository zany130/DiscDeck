# DiscDeck

DiscDeck is a controller-first optical disc manager for Decky Loader on Bazzite and Steam Gaming Mode. It can read the drive inventory and, only after an explicit request, mount a filesystem read-only, eject through UDisks2, mount a read-only ISO, or start a Redumper preservation job. A Redumper exit code is not a verified dump. Virtual disc and game launch are not included. A readable inventory is not hardware validation.

A green CI run packages a development ZIP. It does not mount, eject, dump, load a virtual disc, launch a game, or prove that any of those operations work on hardware.

## Phase 0 plugin

The Quick Access panel shows:

- Decky owner and effective UID/GID, public environment constants, and plugin directories
- Python RPC, a `discdeck:changed` probe event, and listener cleanup on dismount
- UDisks2 visibility and optical block devices, without mounting or ejecting
- `/dev/sr*` to `/dev/sg*` mappings taken from sysfs, including a shared USB bridge with two LUNs
- Effective permissions and named ACLs when `getfacl` is available
- Redumper build 772, shipped in the plugin. Dumps do not use a system or container copy. Update Redumper can install a newer official build
- VHBA and CDEmu presence. An inactive daemon is not started
- Steam and Proton tool discovery. Shortcuts and prefixes are not opened

The normal plugin metadata does not request root. The only flag is `debug`, which the pinned Decky Loader uses to allow reloading.

## Install a development ZIP

CI uploads `DiscDeck-phase0-dev-<full-sha>` after the checks pass. Download that artifact from the workflow run. On the gaming PC:

1. Enable **Developer mode** in Decky Loader’s General settings.
2. Open **Settings → Developer → Third-Party Plugins**.
3. Use **Install Plugin from ZIP File**, or **Install Plugin from URL** once a permanent URL is publishing.

The ZIP is not hardware-validated because CI passed. After installation, open DiscDeck and use **Refresh diagnostics**. Leave the result as an observation until the gates in [docs/host-compatibility-matrix.md](docs/host-compatibility-matrix.md) are exercised on the machine.

## Permanent install URL

The development channel is designed to stay at one HTTPS address. Until a custom domain is confirmed, a public repository can publish:

`https://github.com/zany130/DiscDeck/releases/download/discdeck-dev/DiscDeck.zip`

That address starts working only after the development publish job succeeds. It is a development build, not the stable channel. Setup, atomic replacement, and the optional Cloudflare path are in [docs/distribution.md](docs/distribution.md).

## Development

The project is based on `SteamDeckHomebrew/decky-plugin-template` commit `90d0780e882a17f5714fc6de044c645f22608290`. Build and test instructions are in [docs/development.md](docs/development.md). Phase 0 evidence is in [docs/evidence-ledger.md](docs/evidence-ledger.md) and [docs/phase0-report.md](docs/phase0-report.md).

Python diagnostics live in `py_modules/discdeck` because that is the import path the pinned loader adds. The template’s example C backend is not part of DiscDeck.
