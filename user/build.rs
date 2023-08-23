// use std::env;
// use std::fs::{read_to_string, File};
// use std::io::BufWriter;
// use std::io::Write;
// use std::path::Path;

extern crate protobuf_codegen;

fn main() {
    protobuf_codegen::Codegen::new()
        // Use `protoc` parser, optional.
        .protoc()
        // Use `protoc-bin-vendored` bundled protoc command, optional.
        // .protoc_path(&protoc_bin_vendored::protoc_bin_path().unwrap())
        // All inputs and imports from the inputs must reside in `includes` directories.
        .includes(&["proto"])
        // Inputs must reside in some of include paths.
        // .input("proto/wandb_base.proto")
        // .input("proto/wandb_internal.proto")
        .input("proto/wandb_settings.proto")
        // Specify output directory relative to Cargo output directory.
        .cargo_out_dir("proto")
        .run_from_script();

    // let out_dir_env = env::var_os("OUT_DIR").unwrap();
    // let out_dir = Path::new(&out_dir_env);
    //
    // protobuf_codegen::Codegen::new()
    //     // Use `protoc` parser, optional.
    //     .protoc()
    //     // Use `protoc-bin-vendored` bundled protoc command, optional.
    //     // .protoc_path(&protoc_bin_vendored::protoc_bin_path().unwrap())
    //     // All inputs and imports from the inputs must reside in `includes` directories.
    //     .includes(&["proto"])
    //     // Inputs must reside in some of include paths.
    //     // .input("proto/wandb_base.proto")
    //     .input("proto/wandb_internal.proto")
    //     // Specify output directory relative to Cargo output directory.
    //     // .cargo_out_dir("proto")
    //     .cargo_out_dir(out_dir.to_str().unwrap())
    //     .run_from_script();
    //
    // // Resolve the path to the generated file.
    // let path = out_dir.join("wandb_internal.rs");
    // // Read the generated code to a string.
    // let code = read_to_string(&path).expect("Failed to read generated file");
    // // Write filtered lines to the same file.
    // let mut writer = BufWriter::new(File::create(path).unwrap());
    // for line in code.lines() {
    //     if !line.starts_with("//!") && !line.starts_with("#!") {
    //         writer.write_all(line.as_bytes()).unwrap();
    //         writer.write_all(&[b'\n']).unwrap();
    //     }
    // }
}
