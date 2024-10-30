use std::env;
use std::fs;
use std::io::Result;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use tempfile::tempdir;

fn main() -> Result<()> {
    // proto magic
    let protos = [
        "../../wandb/proto/wandb_base.proto",
        "../../wandb/proto/wandb_settings.proto",
        "../../wandb/proto/wandb_telemetry.proto",
        "../../wandb/proto/wandb_internal.proto",
        "../../wandb/proto/wandb_server.proto",
    ];
    let temp_dir = tempdir().expect("Could not create temp dir");
    let mut temp_files = Vec::new();

    for proto in &protos {
        let content = fs::read_to_string(proto).expect("Could not read proto file");
        let modified_content = content.replace("wandb/proto/", "");

        let file_name = Path::new(proto).file_name().unwrap();
        let temp_file_path = temp_dir.path().join(file_name);

        fs::write(&temp_file_path, modified_content).expect("Could not write to temp file");
        temp_files.push(temp_file_path);
    }

    let temp_paths: Vec<_> = temp_files.iter().map(|f| f.to_str().unwrap()).collect();
    let includes = [temp_dir.path().to_str().unwrap()];

    let mut config = prost_build::Config::new();
    config.out_dir("src");
    config.compile_protos(&temp_paths, &includes).unwrap();

    // Build wandb-core Go binary
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let go_src_dir = manifest_dir.join("../../core");
    let binary_dir = manifest_dir.join("bin");

    let binary_name = if cfg!(windows) {
        "wandb-core.exe"
    } else {
        "wandb-core"
    };

    let wandb_core_path = binary_dir.join(binary_name);

    // if bin directory doesn't exist, create it
    if !binary_dir.exists() {
        fs::create_dir(&binary_dir).expect("Failed to create bin directory");
    }

    let status = Command::new("go")
        .current_dir(&go_src_dir)
        .args([
            "build",
            "-ldflags=-s -w",
            "-mod=vendor",
            "-o",
            wandb_core_path.to_str().unwrap(),
            "cmd/wandb-core/main.go",
        ])
        .status()
        .expect("Failed to execute go build command");

    if !status.success() {
        panic!("Failed to build Go binary");
    }

    // Make the binary path available to the Rust code
    println!(
        "cargo:rustc-env=_WANDB_CORE_PATH={}",
        wandb_core_path.display()
    );

    Ok(())
}
