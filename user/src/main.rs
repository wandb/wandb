mod wandb_settings;

fn main() {
    // create a sample message and print it
    let msg = wandb_settings::Settings::new();
    // print
    println!("msg: {:?}", msg);
}
