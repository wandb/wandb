use std::fs;
use std::io::Result;
use std::path::Path;
use tempfile::tempdir;

fn main() -> Result<()> {
    // proto magic
    let protos = [
        "../../wandb/proto/wandb_base.proto",
        "../../wandb/proto/wandb_settings.proto",
        "../../wandb/proto/wandb_telemetry.proto",
        "../../wandb/proto/wandb_internal.proto",
        "../../wandb/proto/wandb_sync.proto",
        "../../wandb/proto/wandb_api.proto",
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

    // TODO: build wandb-core here and
    //  - either place it under wandbrs/ and use the env var to point to it like we do now
    //  - or embed as in https://zameermanji.com/blog/2021/6/17/embedding-a-rust-binary-in-another-rust-binary

    let bin_paths = ["../../wandb/bin/wandb-core", "../../wandb/bin/gpu_stats"];
    for bin_path in &bin_paths {
        let bin_name = Path::new(bin_path).file_name().unwrap();
        let dest_path = Path::new("bin").join(bin_name);
        // try copying the binary to the wandbrs directory. if doesn't exist, just continue
        if let Err(e) = fs::copy(bin_path, dest_path) {
            eprintln!("Error copying binary: {}", e);
        }
    }

    Ok(())
}
