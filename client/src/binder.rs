use std::collections::HashMap;

use wandbinder::session;

fn main() {
    let settings = session::Settings::new(None);

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
