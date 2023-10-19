// use sentry;
use std::collections::HashMap;
use std::time::Duration;
// use std::io;

use std::thread;

use wandbinder::{printer, session};

fn main() {
    // let _guard = sentry::init(
    //     "https://9e9d0694aa7ccd41aeb5bc34aadd716a@o151352.ingest.sentry.io/4506068829470720",
    // );
    // sentry::capture_error(&io::Error::new(io::ErrorKind::Other, "LOL HAI I AM ERROR"));

    let settings = session::Settings::new(None, Some(1.0), Some(1));

    let session = session::Session::new(settings);

    let mut run = session.init_run(None);

    let name = "glorious-capybara-23";
    let url = "https://wandb.ai/dimaduev/uncategorized/runs/KEHHBT";

    printer::print_header(name, url);

    let mut data: HashMap<String, f64> = HashMap::new();
    data.insert("loss".to_string(), 13.37);

    run.log(data);
    println!("\nLogging to run {}...\n", run.id);
    thread::sleep(Duration::from_secs(2));

    run.finish();

    printer::print_footer(name, url, "/Users/.wandb/run-20201231_123456");
}
