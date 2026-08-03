# W&B Rust SDK (Experimental)

An experimental Rust client for [Weights & Biases](https://wandb.ai/), the AI
developer platform.

Like the Python SDK, this crate is a thin client for the `wandb-core` service,
which it starts as a child process and talks to over a Unix domain socket
(TCP on Windows). It supports authentication with an API key or a JWT identity
token, logging metrics to a run's history, and updating a run's config and
summary — online or offline.

## Usage

The `wandb-core` binary is required at runtime. It ships with the
[`wandb` Python package](https://pypi.org/project/wandb/) (`wandb/bin/wandb-core`
inside the package); point the `WANDB_CORE_PATH` environment variable at it,
or put it on your `PATH`.

```rust
use serde_json::json;

fn main() -> wandb::Result<()> {
    let run = wandb::init(wandb::Settings {
        project: Some("my-project".to_string()),
        ..Default::default()
    })?;

    run.update_config(json!({"learning_rate": 3e-4, "batch_size": 64}))?;
    for step in 1..=10 {
        run.log(json!({"loss": 1.0 / step as f64}))?;
    }
    run.update_summary(json!({"final_score": 0.9}))?;

    run.finish()
}
```

See `examples/basic` for a complete example, including hosting several runs in
one `wandb::Session` and verifying credentials with `Session::authenticate`.

Settings fall back to the same `WANDB_*` environment variables as the Python
SDK (`WANDB_API_KEY`, `WANDB_BASE_URL`, `WANDB_PROJECT`, `WANDB_MODE`, ...).
API keys stored by `wandb login` in `~/.netrc` are picked up automatically,
and JWT identity federation is supported via `WANDB_IDENTITY_TOKEN_FILE`.

## Development

The protobuf bindings in `src/wandb_internal.rs` are generated from
`wandb/proto/*.proto` and committed, so building the crate requires neither
`protoc` nor the rest of this repository. After changing the protos, refresh
the bindings (requires `protoc`):

```sh
cargo run --bin build_proto --features proto-gen
```

Run the tests and the example:

```sh
cargo test
./examples/basic/build_and_run.sh   # runs against a real wandb-core
```

The example is exercised end-to-end against a local W&B test server in CI by
`tests/system_tests/test_experimental/test_client_rust.py`.

## Publishing to crates.io

The crate is self-contained (committed proto bindings, no build script), so
publishing is the standard flow from this directory:

```sh
cargo publish --dry-run   # verify the package builds in isolation
cargo publish
```

Remember to bump `version` in `Cargo.toml` first; crates.io versions are
immutable and can only be yanked, never replaced.
