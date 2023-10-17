use std::{collections::HashMap, env};

use wandbinder::{session, wandb_internal};

fn main() {
    let settings = wandb_internal::Settings {
        base_url: Some("https://api.wandb.ai".to_string()),
        // stats_sample_rate_seconds: Some(1.0),
        // stats_samples_to_average: Some(1),
        log_internal: Some("wandb-internal.log".to_string()),
        sync_file: Some("lol.wandb".to_string()),
        ..Default::default()
    };

    let session = session::Session::new(settings);

    let mut run = session.new_run(None);
    println!("Run id: {}", run.id);

    let mut data: HashMap<String, f64> = HashMap::new();
    data.insert("loss".to_string(), 13.37);

    run.log(data);

    // sleep
    std::thread::sleep(std::time::Duration::from_secs(5));

    run.finish();
}
