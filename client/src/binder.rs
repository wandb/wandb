// use sentry;
use std::collections::HashMap;
// use std::io;

use wandbinder::session;

fn main() {
    // let _guard = sentry::init(
    //     "https://9e9d0694aa7ccd41aeb5bc34aadd716a@o151352.ingest.sentry.io/4506068829470720",
    // );
    // sentry::capture_error(&io::Error::new(io::ErrorKind::Other, "LOL HAI I AM ERROR"));

    let settings = session::Settings::new(None, Some(1.0), Some(1));

    let session = session::Session::new(settings);

    let mut run = session.init_run(None);
    println!("Run id: {}", run.id);

    let mut data: HashMap<String, f64> = HashMap::new();
    data.insert("loss".to_string(), 13.37);

    run.log(data);

    // sleep
    // std::thread::sleep(std::time::Duration::from_secs(5));

    run.finish();
}
