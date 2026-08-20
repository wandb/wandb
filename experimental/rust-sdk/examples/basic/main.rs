//! Basic usage of the W&B Rust SDK: authenticate, then create a run and
//! log config, metrics, and summary values to it.
//!
//! Run with: cargo run --example basic

use serde_json::json;

fn main() -> wandb::Result<()> {
    let settings = wandb::Settings {
        project: Some("rust".to_string()),
        run_tags: Some(vec!["r".to_string(), "ust".to_string()]),
        ..Default::default()
    };
    let online = settings.mode() == wandb::Mode::Online;
    let session = wandb::Session::new(settings)?;

    // Verify the API key (offline mode needs no credentials).
    if online {
        let entity = session.authenticate()?;
        println!("Logged in with default entity: {entity}");
    }

    let run = session.init_run()?;
    run.update_config(json!({"batch_size": 64, "learning_rate": 3e-4}))?;

    for epoch in 1..=4 {
        run.log(json!({
            "loss": 1.0 / epoch as f64,
            "recall": 1.0 - 0.5 / epoch as f64,
            "epoch": epoch,
        }))?;
    }

    run.update_summary(json!({"best_recall": 0.875}))?;
    println!("Final summary: {}", run.summary()?);

    run.finish()
}
