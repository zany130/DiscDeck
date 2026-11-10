# Development

Phase 0 uses the official Decky template toolchain: pnpm 9.15.9, Node 22, Rollup 4.53.3, TypeScript 5.6.2, and Python 3.12 for local checks. The plugin itself imports only the Python standard library so a Decky install does not need extra packages.

## Install and check

```bash
corepack prepare pnpm@9.15.9 --activate
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run lint
pnpm test
PYTHONPATH=py_modules:. python3 -m unittest discover -s tests -t .
node --test distribution/worker.test.mjs
pnpm run build
python3 scripts/package_plugin.py --output out
python3 scripts/verify_zip.py out/DiscDeck-phase0-dev-*.zip
```

`pnpm run typecheck` sets `skipLibCheck` so the pinned `@decky/api` and `react-icons` declaration gaps do not fail the project check. DiscDeck’s own sources stay strict.

Frontend tests use Vitest. Python tests use `unittest`. Both run without optical hardware. Device fixtures are synthetic sysfs trees shaped like the measured host inventory.

## Layout

- `main.py` is the Decky `Plugin` class: lifecycle and thin RPC methods.
- `py_modules/discdeck/` holds the diagnostic adapters. The loader appends `py_modules` to `sys.path`.
- `src/` is the Quick Access UI. It uses public `@decky/api` and `@decky/ui` exports only.
- `scripts/package_plugin.py` reproduces the Decky CLI ZIP layout without Docker.
- `distribution/` is the unpublished Cloudflare Worker.

The template’s `backend/` directory is a Docker-built C example. DiscDeck does not ship a native backend, so that directory is not present. Keeping it would make the official CLI try to compile `hello` into `bin/`.

The VS Code deploy example under `.vscode/defsettings.json` still contains the template’s `/home/deck` placeholder. DiscDeck does not read that file and does not use it as a storage path.

## Packaging

The ZIP root is `DiscDeck/` and contains `dist/index.js`, `plugin.json`, `package.json`, `main.py`, `LICENSE`, `README.md`, and `py_modules/`. Files under `defaults/` are flattened into that root, matching Decky CLI 0.0.8. The packaged `build_info.json` records the git commit and sets `hardware_validated` to false.

## CI

`.github/workflows/ci.yml` runs on pull requests and on pushes to `main` and `cursor/phase0-foundation-beb3`. It installs the lockfile, runs the checks above, builds the ZIP, verifies it, and uploads `DiscDeck-phase0-dev-<full-sha>`.

The publish job runs only for a push whose branch is in `DISCDECK_PUBLISH_BRANCHES` (default `main,cursor/phase0-foundation-beb3`). See [distribution.md](distribution.md).

## Safety boundaries

Do not add the `root` plugin flag. Do not call `modprobe`, start `cdemu-daemon`, mount or eject, run `redumper disc`, or edit Steam files from a diagnostic probe. New host commands have to go through `discdeck.security.assert_readonly_argv`.
