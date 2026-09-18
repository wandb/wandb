//! Decodes a .wandb file with the app's ingest pipeline and reports
//! throughput: `cargo run --release -p leet-ingest --example bench -- run.wandb`.

use std::path::Path;
use std::time::Instant;

fn main() {
    let path = std::env::args().nth(1).expect("usage: bench <run.wandb>");
    let path = Path::new(&path);
    let start = Instant::now();
    let (mut records, mut keys, mut points) = (0usize, 0usize, 0usize);
    leet_ingest::decode(path, |batch| {
        records += batch.records;
        keys += batch.metrics.new_keys.len();
        points += batch.metrics.x.len();
        batch.recycle();
        true
    });
    let secs = start.elapsed().as_secs_f64();
    let bytes = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    println!(
        "{records} records, {keys} metrics, {points} points in {secs:.3}s: {:.0} MB/s, {:.1} M points/s",
        bytes as f64 / 1e6 / secs,
        points as f64 / 1e6 / secs,
    );
}
