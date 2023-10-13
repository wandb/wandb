mod session;
mod wandb_internal;

fn main() {
    println!("Hello, world!");
    // println!(
    //     "{:?}",
    //     wandb_internal::Settings {
    //         base_url: Some("https://google.com".to_string()),
    //         ..Default::default()
    //     }
    // );
    // println!(
    //     "{:?}",
    //     wandb_internal::RequestInfo {
    //         ..Default::default()
    //     }
    // );
    // println!(
    //     "{:?}",
    //     wandb_internal::ServerShutdownRequest {
    //         ..Default::default()
    //     }
    // );

    let settings = wandb_internal::Settings {
        base_url: Some("https://api.wandb.ai".to_string()),
        log_internal: Some("wandb-internal.log".to_string()),
        sync_file: Some("/Users/dimaduev/dev/sdk/client/lol.wandb".to_string()),
        ..Default::default()
    };

    let addr = "127.0.0.1:50171";
    let session = session::Session::new(settings, addr.to_string());

    let run = session.new_run(None);
    println!("Run id: {}", run.id);
    run.log();
    run.finish();
}
