// use sentry;
use std::collections::HashMap;
use std::time::Duration;
// use std::io;

use std::thread;

use wandbinder::{session, settings};

fn main() {
    // let _guard = sentry::init(
    //     "https://9e9d0694aa7ccd41aeb5bc34aadd716a@o151352.ingest.sentry.io/4506068829470720",
    // );
    // sentry::capture_error(&io::Error::new(io::ErrorKind::Other, "LOL HAI I AM ERROR"));

    let settings = settings::Settings::new(None, Some(1.0), Some(1));

    let mut session = session::Session::new(settings);

    let mut run = session.init_run(None);

    println!();
    for i in 0..5 {
        println!("Epoch {}", i);
        let mut data = HashMap::new();
        data.insert("loss".to_string(), 1.0 / (i + 1) as f64);
        run.log(data);
        thread::sleep(Duration::from_millis(250));
    }
    println!();

    run.finish();
}
