//! Decodes a .wandb file with the app's ingest path and reports throughput:
//! `cargo run --release -p leet-ingest --example bench -- run.wandb`.

use std::time::Instant;

use leet_ingest::Decoder;
use leet_wire::transaction_log::open_reader;

fn main() {
    let path = std::env::args().nth(1).expect("usage: bench <run.wandb>");
    let start = Instant::now();
    let mut reader = open_reader(&path).expect("open the transaction log");
    let mut decoder = Decoder::default();
    let mut records = 0usize;
    loop {
        match reader.read() {
            Ok(record) => {
                decoder.record(record);
                records += 1;
            }
            Err(err) if err.is_eof() || err.is_unexpected_eof() => break,
            Err(_) => {}
        }
    }
    let batch = decoder.flush(true);
    let points: usize = batch.metrics.iter().map(|column| column.x.len()).sum();
    let secs = start.elapsed().as_secs_f64();
    let bytes = std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
    println!(
        "{records} records, {} metrics, {points} points in {secs:.2}s: {:.1} MB/s, {:.1} M points/s",
        batch.metric_keys.len(),
        bytes as f64 / 1e6 / secs,
        points as f64 / 1e6 / secs,
    );
}
