use std::collections::HashMap;
use wandb;

fn main() {
    let project = Some("test-rust".to_string());
    let settings = Some(wandb::settings::Settings::default());
    let mut run = wandb::init(project, settings).unwrap();

    let mut data = HashMap::new();
    data.insert("accuracy".to_string(), wandb::run::Value::Float(0.9));
    data.insert("loss".to_string(), wandb::run::Value::Float(0.1));
    run.log(data);
    run.finish();
}
