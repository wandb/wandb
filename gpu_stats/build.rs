use std::fs;
use std::io::Result;
use std::path::{Path, PathBuf};
use tempfile::tempdir;

fn main() -> Result<()> {
    // Get the path to the directory containing Cargo.toml
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());

    let proto_dir = manifest_dir.join("..").join("wandb").join("proto");
    let protos = [
        proto_dir.join("wandb_base.proto"),
        proto_dir.join("wandb_telemetry.proto"),
        proto_dir.join("wandb_internal.proto"),
        proto_dir.join("wandb_system_monitor.proto"),
    ];

    // Create a temporary directory to store modified .proto files
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

    // Convert file paths to strings
    let temp_paths: Vec<_> = temp_files.iter().map(|f| f.to_str().unwrap()).collect();
    let includes = [temp_dir.path().to_str().unwrap()];

    let out_dir = manifest_dir.join("src");
    let descriptor_path = out_dir.join("descriptor.bin");

    // Use tonic_build to compile .proto files and generate gRPC code
    tonic_build::configure()
        .build_server(true) // Generate server code
        .out_dir(out_dir) // Specify the output directory
        .file_descriptor_set_path(descriptor_path) // Generate a file descriptor set
        .compile_protos(&temp_paths, &includes)
        .unwrap_or_else(|e| panic!("Failed to compile protos {:?}", e));

    Ok(())
}
