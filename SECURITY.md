# Security Policy

## Reporting a Vulnerability

Please report all vulnerabilities to security@coreweave.com.

## Known Vulnerabilities in Dependencies

The `### Security` section of each release in [CHANGELOG.md](CHANGELOG.md), which is also the text of the release notes on GitHub, lists the known vulnerabilities fixed since the previous release by updating the Go version and the Go modules in [`core/go.mod`](core/go.mod) that the `wandb-core` binary is built with. Each is listed by its CVE ID and linked to its entry in the [Go vulnerability database](https://pkg.go.dev/vuln/). The list comes from `govulncheck -scan module`, run in `core/` before and after each dependency update, and includes vulnerabilities in modules whose affected code `wandb-core` does not call. Changes to the Python dependency ranges in [`pyproject.toml`](pyproject.toml) that exclude a vulnerable version are listed in the same section.
