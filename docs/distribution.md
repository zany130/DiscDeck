# Distribution

DiscDeck keeps two channels:

| Channel | Pointer | GitHub release tag | When it updates |
|---|---|---|---|
| Development | `dev/latest.json` and `dev/DiscDeck.zip` | `discdeck-dev` | After CI passes on an allowlisted branch |
| Stable | `stable/latest.json` and `stable/DiscDeck.zip` | `discdeck-stable` | Only a manual workflow with an extra confirmation flag |

A failed or incomplete build never writes the channel pointer. The unique ZIP is uploaded and checked first. The pointer or canonical `DiscDeck.zip` asset moves only after that check. Development publishes do not write `stable/`.

CI success still does not mean the ZIP was tried on optical hardware. `build_info.json` and the publish metadata keep `hardware_validated` false. Neither file contains host diagnostics, home directories, or credentials.

## URL Decky can install

Decky Loader v3.3.1 downloads an install URL with an HTTP GET and accepts the body only when the status is 200 and the bytes are a ZIP. Redirects are followed. The URL must be `http` or `https`.

Until a custom domain is confirmed, the working public address for a **public** repository is:

`https://github.com/zany130/DiscDeck/releases/download/discdeck-dev/DiscDeck.zip`

That URL is constant. Each successful development publish replaces the `DiscDeck.zip` asset on the `discdeck-dev` prerelease only after a uniquely named asset for the same commit has been uploaded and downloaded back with a matching SHA-256. The unique asset name is `DiscDeck-phase0-dev-<short-sha>.zip`. `metadata.json` on the same release records the commit.

This GitHub replacement is not a single object-store copy. If the canonical upload fails after GitHub deletes the previous asset, the unique asset and the previous metadata remain, and the next successful run restores `DiscDeck.zip`. Cloudflare R2 avoids that window: the worker reads `dev/latest.json`, and that pointer is written only after the unique object upload succeeds.

The stable URL, when a stable publish is eventually enabled, is:

`https://github.com/zany130/DiscDeck/releases/download/discdeck-stable/DiscDeck.zip`

Do not run the stable workflow for this Phase 0 build unless you intend to replace that stable URL. The workflow does nothing unless the repository variable `DISCDECK_STABLE_PUBLISH_ENABLED` is `true` and the dispatch confirmation is `replace-stable-discdeck`.

No custom domain is configured. `diskdecky.dev` is not assumed. Set the public base URL only after the hostname is owned and DNS is delegated.

## What already runs

On a push to an allowlisted branch, CI publishes with `DISCDECK_PUBLISH_MODE`:

- `auto` (the default when the variable is unset): use R2 when all R2 secrets exist, otherwise use a GitHub release when the repository is public.
- `r2`: require R2 secrets; skip publication if they are absent.
- `github-release`: require a public repository. A private repository refuses this mode because Decky cannot download a private release asset without authentication.
- `none`: do not publish.

The Actions artifact is always uploaded after tests, even when publication is skipped. Download it from the workflow run. Its name is `DiscDeck-phase0-dev-<full-sha>`.

## Cloudflare R2 and Worker

Use this when the GitHub release URL should be replaced by a domain you control.

1. Create an R2 bucket named `discdeck-artifacts` (or set `R2_BUCKET` to the name you chose).
2. Create an API token that can read and write objects in that bucket only.
3. Add repository secrets `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET`.
4. Set the repository variable `DISCDECK_PUBLISH_MODE` to `r2` or leave it unset (`auto`).
5. From a machine that is allowed to deploy Workers, run `npx wrangler deploy` in `distribution/` after `wrangler login`. `distribution/wrangler.toml` binds the bucket as `BUCKET` and does not set a route.
6. Confirm the hostname, then add a Worker route for that zone. Do not invent the DNS name in the repository.
7. Point the route at `/dev/*` and, separately, `/stable/*`.
8. The install URL is `https://<confirmed-host>/dev/DiscDeck.zip`. The worker returns the ZIP named by `dev/latest.json` with `Content-Type: application/zip` and `Cache-Control: no-store`.

The worker source is `distribution/worker.mjs`. It does not list the bucket and it rejects a pointer whose object key is outside the requested channel.

## GitHub variable reference

| Name | Purpose |
|---|---|
| `DISCDECK_PUBLISH_BRANCHES` | Comma-separated branch names allowed to publish development builds. Default `main,cursor/phase0-foundation-beb3,cursor/phase2-iso-library-beb3,cursor/phase3-redumper-beb3`. The workflow trigger list must include those branches too. |
| `DISCDECK_PUBLISH_MODE` | `auto`, `r2`, `github-release`, or `none`. |
| `DISCDECK_STABLE_PUBLISH_ENABLED` | Must be `true` before the manual stable workflow can run. Leave it unset during Phase 0. |

## Install on Bazzite

Nothing in this repository installs itself on the gaming PC.

1. Enable **Developer mode**.
2. Open **Settings → Developer → Third-Party Plugins**.
3. For a local artifact, choose **Install Plugin from ZIP File**.
4. For the published channel, choose **Install Plugin from URL** and enter the development URL above.
5. Decky shows a third-party warning. The ZIP is a development diagnostic build.
6. Open the DiscDeck Quick Access menu and refresh. Treat every hardware line as unproven until the host gates are run deliberately.
