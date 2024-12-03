use std::fs;
use std::io::Result;
use std::path::Path;
use tempfile::tempdir;

fn main() -> Result<()> {
    // Paths to your .proto files
    let protos = [
        "../wandb/proto/wandb_base.proto",
        "../wandb/proto/wandb_telemetry.proto",
        "../wandb/proto/wandb_internal.proto",
        "../wandb/proto/wandb_system_monitor.proto",
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

    // Use tonic_build to compile .proto files and generate gRPC code
    tonic_build::configure()
        .build_server(true) // Generate server code
        // .build_client(true) // Generate client code
        .out_dir("src") // Specify the output directory
        .file_descriptor_set_path("src/descriptor.bin") // Save the descriptor
        .compile_protos(&temp_paths, &includes)
        .unwrap_or_else(|e| panic!("Failed to compile protos {:?}", e));

    Ok(())
}
