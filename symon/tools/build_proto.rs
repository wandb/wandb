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

    // ---- wandb internal protos ----

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

    let temp_paths: Vec<_> = temp_files.iter().map(|f| f.to_str().unwrap()).collect();
    let includes = [temp_dir.path().to_str().unwrap()];

    tonic_prost_build::configure()
        .build_server(true)
        .out_dir(&src_dir)
        .compile_protos(&temp_paths, &includes)
        .unwrap_or_else(|e| panic!("Failed to compile wandb protos {:?}", e));

    // ---- TPU runtime metric service proto ----

    let tpu_proto_dir = project_root.join("proto");
    let tpu_proto = tpu_proto_dir.join("tpu_metric_service.proto");

    tonic_prost_build::configure()
        .build_server(false)
        .build_client(true)
        .out_dir(&src_dir)
        .compile_protos(
            &[tpu_proto.to_str().unwrap()],
            &[tpu_proto_dir.to_str().unwrap()],
        )
        .unwrap_or_else(|e| panic!("Failed to compile TPU protos {:?}", e));

    Ok(())
}
