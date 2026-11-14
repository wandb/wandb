# Temporary copy of the CES Go SDK: do not merge

> [!WARNING]
> TODO: Delete this directory and the `replace` directive in `core/go.mod`
> once `github.com/wandb/cwevals-go` publishes a release, and require that
> version instead. This copy exists only for early development and must not
> be merged.

This is a copy of the CoreWeave Evaluations (CES) Go SDK `v0.0.1-beta.3`, as
prepared for release in a local `wandb/cwevals-go` checkout by wandb/core's
`.github/scripts/evaluations-publish-go-sdk.sh prepare`, without the files that
only run the SDK's own tooling.

To refresh it from a prepared `wandb/cwevals-go` checkout at `$CWEVALS`:

```bash
rsync -a --delete --exclude .git --exclude .github --exclude examples --exclude scripts --exclude lib --exclude Brewfile --exclude .devcontainer --exclude .stats.yml --exclude .gitignore --exclude VENDORED_DO_NOT_MERGE.md "$CWEVALS"/ core/third_party/cwevals-go/
cd core && go mod tidy && go mod vendor
```
