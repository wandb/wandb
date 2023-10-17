mod connection;
mod run;
mod session;
mod wandb_internal;

use std::{collections::HashMap, env};

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
        // stats_sample_rate_seconds: Some(1.0),
        // stats_samples_to_average: Some(1),
        log_internal: Some("wandb-internal.log".to_string()),
        sync_file: Some("lol.wandb".to_string()),
        ..Default::default()
    };

    let addr = format!("127.0.0.1:{}", port);
    let session = session::Session::new(settings, addr.to_string());

    let mut run = session.new_run(None);
    println!("Run id: {}", run.id);

    let mut data: HashMap<String, f64> = HashMap::new();
    data.insert("loss".to_string(), 13.37);

    run.log(data);

    // sleep
    std::thread::sleep(std::time::Duration::from_secs(5));

    run.finish();
}
