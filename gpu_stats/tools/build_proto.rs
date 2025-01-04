//! Generate protobuf bindings for the wandb proto files for the System Metrics service.
use std::fs;
use std::io::Result;
use std::path::Path;
use tempfile::tempdir;

fn main() -> Result<()> {
    let current_dir = Path::new(file!()).parent().unwrap();
    let project_root = current_dir.join("..").canonicalize().unwrap();
    let proto_dir = project_root.join("../wandb/proto");
    let src_dir = project_root.join("src");
    // let descriptor = src_dir.join("descriptor.bin");

    let proto_files = [
        "wandb_base.proto",
        "wandb_telemetry.proto",
        "wandb_internal.proto",
        "wandb_system_monitor.proto",
    ];

    let protos: Vec<_> = proto_files
        .iter()
        .map(|file| proto_dir.join(file))
        .collect();

    // Remove the "wandb/proto/" prefix from the import statements in the proto files.
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

    // The generated code will be written to the src/wandb_internal.rs file.
    tonic_build::configure()
        .build_server(true) // Generate server code
        .out_dir(&src_dir) // Specify the output directory
        // .file_descriptor_set_path(&descriptor) // Save the descriptor
        .compile_protos(&temp_paths, &includes)
        .unwrap_or_else(|e| panic!("Failed to compile protos {:?}", e));

    Ok(())
}
