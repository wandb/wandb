//! Regenerates `src/wandb_internal.rs` from the wandb proto files.
//!
//! The generated file is committed so that the crate builds without protoc
//! and without the rest of this repository (e.g. when published to
//! crates.io). Rerun this tool whenever the protos in `wandb/proto/` change:
//!
//!     cargo run --bin build_proto --features proto-gen

use std::fs;
use std::path::Path;

fn main() -> std::io::Result<()> {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let proto_dir = manifest_dir.join("../../wandb/proto").canonicalize()?;

    let proto_files = [
        "wandb_base.proto",
        "wandb_settings.proto",
        "wandb_telemetry.proto",
        "wandb_internal.proto",
        "wandb_api.proto",
        "wandb_sync.proto",
        "wandb_server.proto",
    ];

    // The proto files import each other with a "wandb/proto/" prefix that
    // doesn't exist relative to any include root; strip it in temp copies.
    let temp_dir = tempfile::tempdir()?;
    let mut temp_paths = Vec::new();
    for name in proto_files {
        let content = fs::read_to_string(proto_dir.join(name))?;
        let temp_path = temp_dir.path().join(name);
        fs::write(&temp_path, content.replace("wandb/proto/", ""))?;
        temp_paths.push(temp_path);
    }

    let mut config = prost_build::Config::new();
    config.out_dir(manifest_dir.join("src"));
    config.compile_protos(&temp_paths, &[temp_dir.path().to_path_buf()])
}
