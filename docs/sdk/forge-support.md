# CoreWeave Forge SDK readiness

**Internal / embargoed. Prepared September 15, 2026. Keep this branch local until
the September 30 announcement is authorized. Do not publish this document as SDK
documentation or release notes.**

## Conclusion

Existing W&B SDK workloads should continue using `https://api.wandb.ai` without
configuration or credential changes. Forge introduces a new browser shell and an
optional API proxy. Supporting that proxy requires path-aware URLs, login links,
cloud classification, LEET parsing, and telemetry fixes. It does not require
renaming the Python package or changing the API key protocol.

This branch contains a preparatory patch for the confirmed URL and telemetry
issues. Full Forge readiness still depends on the file-transfer and integration
checks below; unit tests alone do not establish production compatibility.

## Evidence and contract

- [Engineering API discussion, August 28](https://coreweave.slack.com/archives/C0BPLUVQM4K/p1787933777926619):
  the browser redirects, while existing API traffic continues without redirects.
  The early suggestion that Forge would expose root `/graphql` is superseded by
  the more precise proxy routing in the backend configuration below.
- [API key discussion](https://coreweave.slack.com/archives/C0BPLUVQM4K/p1787864766339299):
  W&B identity keys continue to use the existing HTTP authentication protocol.
  Alternative environment variable names were discussed, not settled.
- [Marketing Channel Copy, Channel Messaging tab](https://docs.google.com/document/d/1CjDqWWvfSldkkx3lKlrfzthzQuxk4GAk2bVH79vn7qM/edit?tab=t.0):
  the approved September 1 copy and engineering comments promise uninterrupted
  API/SDK use. The September 30 draft still asks users to change API hosts and
  contains an unresolved redirect-duration placeholder. Reconcile that draft
  before release; it is not a reason to change SDK defaults.
- [Internal FAQ](https://docs.google.com/document/d/1XSgXjRZjNdTwOHRiHrxnuLFHF2nxsn0I9ZHtY-nX0eA/edit?tab=t.f7uk6uhktm5k):
  dedicated-instance domains and IPs stay unchanged. Forge for dedicated/on-prem
  deployments has no settled launch contract in the reviewed material.
- [September 14 backend PR](https://github.com/wandb/core/pull/54198) and its
  [production routing configuration](https://github.com/wandb/core/blob/85f7b80e53b2111cc339c21ed29a6605038950c3/terraform/pasture/environments/prod/platform/host/main.tf):
  `/api/wandb` proxies to `api.wandb.ai`, stripping that prefix. `/files`,
  `/artifacts`, and `/artifactsV2` are separate proxy routes. Root `/graphql` is
  not an API route. This is source evidence, not a live end-to-end deployment test.
- [W&B shell routes](https://github.com/wandb/core/blob/85f7b80e53b2111cc339c21ed29a6605038950c3/frontends/app/forge-routes.json):
  `/wandb` mounts the existing W&B app. Other products and account management
  have separate routes.
- [Authorization page](https://github.com/wandb/core/blob/85f7b80e53b2111cc339c21ed29a6605038950c3/frontends/app/src/routes/auth/authRoutesData.ts):
  W&B's `/authorize` page is under that mount, so the SDK should link to
  `/wandb/authorize`. The shell preserves the destination through identity login.
  Opening the supplied Forge site also showed the `id.coreweave.com` login page
  accepting existing W&B credentials.

| Purpose | Production | QA |
| --- | --- | --- |
| SDK API base | `https://forge.coreweave.com/api/wandb` | `https://qa.forge.coreweave.com/api/wandb` |
| W&B app base | `https://forge.coreweave.com/wandb` | `https://qa.forge.coreweave.com/wandb` |
| API-key authorization page | `https://forge.coreweave.com/wandb/authorize` | `https://qa.forge.coreweave.com/wandb/authorize` |

## Prepared in this branch

| Change | SDK surface | Reason |
| --- | --- | --- |
| Recognize exact production/QA Forge hosts and validate their API prefix and HTTPS | `sdk/lib/urls.py`, `Settings`, `HostUrl` | A bare Forge host would send GraphQL to the shell; report the correct base URL instead. |
| Map the Forge API base to its `/wandb` app mount | `util.api_to_app_url` | Run, project, sweep, report, and ordinary artifact links must point into the W&B app. Explicit app URL overrides still take precedence. |
| Preserve the app path when building authorization links | `sdk/lib/wbauth/prompt.py` | The existing code discarded the mount and produced `/authorize`. |
| Classify production Forge as cloud; recognize Forge in login help | `Settings.is_local`, `wbauth/saas.py` | Avoid treating the new SaaS entry point as a self-hosted server. QA retains the existing nonproduction classification. |
| Reject Forge in self-hosted deployment diagnostics | `sdk/verify/verify.py` | `wandb verify` is not a hosted-service verification command. |
| Convert Forge UI run links to the prefixed API base and preserve it in Go | `cli/leet.py`, `core/internal/leet/remote.go` | Existing parsers only understood an origin followed by entity/project/run. |
| Preserve API path prefixes in Go OpenTelemetry exporters | `core/internal/analytics/opentelemetryproxy.go` | Exporter path options previously replaced the prefix even though probing used the correct endpoint. |

Tests cover the new routes, existing W&B/custom-host behavior, invalid and
lookalike hosts, app URL overrides, authorization links, host-scoped netrc
credentials, LEET parsing, and actual telemetry requests to a local test server.

### Validation performed

- 366 Python tests passed and 15 were skipped across the URL, authentication,
  settings, utility, verification, and LEET suites. Two existing offline-service
  tests needed a rerun with permission to bind local IPC sockets; both passed.
- Go `internal/analytics` and `internal/analyticstest` passed, including a
  regression that failed before the telemetry prefix fix.
- Go `internal/leet` tests matching `^TestParseRemoteURL` passed.
- Ruff lint/format checks and `git diff --check` passed. No live Forge training,
  uploads, or other workload writes were performed.

## Remaining implementation and release checks

1. **Authenticated file transfers: establish and test the response contract.**
   `core/internal/wbapi/wbapi.go` and
   `core/internal/leet/parquethistorysource.go` restrict automatic credentials to
   the configured base URL's path through `httplayers.LimitTo`. With a
   `/api/wandb` base, protected sibling `/files`, `/artifacts`, or `/artifactsV2`
   URLs will not receive those credentials. Obtain representative Forge API
   responses and test run files, public API downloads, artifact manifests/blobs,
   and LEET history. If they require credentials on siblings, add a narrowly
   scoped rule for the confirmed W&B routes on the same Forge origin. Do not
   allow credentials on unrelated Forge products, external storage, or redirects
   to another origin.
2. **Root-relative upload URLs:** `Run.upload_file` concatenates the API base
   with `uploadUrl`. `/files/...` becomes `/api/wandb/files/...`; an already
   prefixed `/api/wandb/files/...` would duplicate the prefix. Test actual
   server responses and define consistent resolution for relative, root-relative,
   and absolute signed URLs before changing this behavior.
3. **Exercise the complete proxy flow in QA:** login/verification with existing
   and new keys; GraphQL; `init/log/finish`; resume and offline sync; sweeps;
   file-stream logs; artifacts; public API uploads/downloads; and LEET history.
   Check API requests succeed directly without a browser-login redirect and that
   old SDK versions continue working against the old host. Include non-root
   GraphQL, file-stream, and OIDC token-exchange cases in the integration suite.
4. **Verify browser links with the rollout enabled:** terminal and notebook
   links, `/wandb/authorize` signup/referrer handling through identity login,
   reports, ordinary artifacts, registry links, and account/key-management links.
   Registry/account destinations are separate shell routes; confirm whether old
   W&B registry deep links are translated before rewriting those links in the SDK.
5. **Align launch decisions:** resolve the conflicting customer copy; decide
   whether new key/base-URL environment aliases are wanted and specify precedence
   if both old and new names are present. Any later change to default API/UI
   destinations needs an explicit rollout and credential-migration decision.

GraphQL, file-stream, OIDC exchange, Python telemetry, and artifact fallback
URLs already append to or join with the configured API base. Backend-provided
signed storage URLs already pass through unchanged. These need contract tests,
not an automatic hostname rewrite.

## Compatibility and embargo boundaries

- Keep `wandb`, `import wandb`, `WANDB_*`, protocol field names, HTTP headers,
  User-Agent strings, and Kubernetes labels stable.
- Keep the default API host and `wandb login --cloud` on `api.wandb.ai`.
  Existing users are not required to relogin or update running jobs.
- An explicit Forge login stores a credential for the Forge host; no automatic
  copying or fallback from the legacy host is introduced.
- Preserve dedicated/on-prem routing and explicit `WANDB_APP_URL` /
  `app_url_override` settings.
- Do not push this branch, open a PR, publish packages/docs, or enable a timed
  cutover before the embargo is explicitly lifted.
