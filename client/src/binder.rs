mod session;
mod wandb_internal;
use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();

    // Check if at least one argument is provided
    if args.len() < 2 {
        eprintln!("Usage: {} <argument>", args[0]);
        std::process::exit(1);
    }

    // Access the argument
    // Parse the port argument
    let port: u16 = match args[1].parse() {
        Ok(p) => p,
        Err(_) => {
            eprintln!("Invalid port number: {}", args[1]);
            std::process::exit(1);
        }
    };

    let settings = wandb_internal::Settings {
        base_url: Some("https://api.wandb.ai".to_string()),
        log_internal: Some("wandb-internal.log".to_string()),
        sync_file: Some("lol.wandb".to_string()),
        ..Default::default()
    };

    let addr = format!("127.0.0.1:{}", port);
    let session = session::Session::new(settings, addr.to_string());

    let run = session.new_run(None);
    println!("Run id: {}", run.id);
    run.log();
    run.finish();
    loop {}
}
