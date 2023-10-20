// use sentry;
use std::collections::HashMap;
use std::time::Duration;
// use std::io;

use std::thread;

use wandbinder::{run, session, settings};

fn main() {
    // let _guard = sentry::init(
    //     "https://9e9d0694aa7ccd41aeb5bc34aadd716a@o151352.ingest.sentry.io/4506068829470720",
    // );
    // sentry::capture_error(&io::Error::new(io::ErrorKind::Other, "LOL HAI I AM ERROR"));

    let settings =
        settings::Settings::new(None, Some("offline".to_string()), None, Some(1.0), Some(1));

    let session = session::Session::new(settings);

    let mut run = session.init_run(None);

    println!();
    let mut data = HashMap::new();
    let num_functions = 3;
    let num_points = 10;
    let amplitude = 1.0;
    use std::f64::consts::PI;

    for i in 0..num_points {
        for j in 0..num_functions {
            let phase = 2.0 * PI * j as f64 / num_functions as f64;
            // println!("Epoch {} Batch {}", i, j);
            let v = amplitude * (2.0 * PI * i as f64 / num_points as f64 + phase).sin();
            let k = format!("loss_{}", j);
            data.insert(k, run::Value::Float((v * 1e5).round() / 1e5));
        }
        data.insert("lol".to_string(), run::Value::Str("hi".to_string()));
        run.log(data.clone());
        thread::sleep(Duration::from_millis(5));
    }
    println!();

    run.finish();
}
