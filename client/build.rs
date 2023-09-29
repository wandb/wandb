// fn main() -> Result<(), Box<dyn std::error::Error>> {
//     tonic_build::compile_protos("proto/base.proto")?;
//     Ok(())
// }

use std::io::Result;
fn main() -> Result<()> {
    prost_build::compile_protos(
        &[
            "../wandb/proto/wandb_base.proto",
            "../wandb/proto/wandb_settings.proto",
            "../wandb/proto/wandb_telemetry.proto",
            "../wandb/proto/wandb_internal.proto",
            "../wandb/proto/wandb_server.proto",
        ],
        &["../wandb/proto/"],
    )?;
    Ok(())
}
