//! Smoke test: dump record counts from a real .wandb file.
use std::time::Duration;
use wandb_leet::msg::RecordMsg;

fn main() {
    let path = std::env::args().nth(1).expect("usage: dump <file.wandb>");
    let mut reader = wandb_leet::store::live::HistoryReader::open(&path).unwrap();
    let mut counts = std::collections::BTreeMap::new();
    loop {
        let chunk = reader.read_chunk(100_000, Duration::from_secs(10));
        for m in &chunk.msgs {
            let name = match m {
                RecordMsg::Run(r) => {
                    println!(
                        "run: id={} name={} project={} tags={:?}",
                        r.id, r.display_name, r.project, r.tags
                    );
                    "run"
                }
                RecordMsg::History(h) => {
                    if !counts.contains_key("history") {
                        println!(
                            "history metrics: {:?}",
                            h.metrics.iter().map(|(k, _)| k).collect::<Vec<_>>()
                        );
                        println!(
                            "media: {:?}",
                            h.media
                                .iter()
                                .map(|(k, v)| (k, v.len()))
                                .collect::<Vec<_>>()
                        );
                    }
                    "history"
                }
                RecordMsg::Summary { .. } => "summary",
                RecordMsg::SystemInfo { record, .. } => {
                    println!(
                        "env: os={} host={} cpu_count={} apple={:?}",
                        record.os,
                        record.host,
                        record.cpu_count,
                        record.apple.as_ref().map(|a| &a.name)
                    );
                    "env"
                }
                RecordMsg::Stats(s) => {
                    if !counts.contains_key("stats") {
                        println!(
                            "stats keys: {:?}",
                            s.metrics.iter().map(|(k, _)| k).collect::<Vec<_>>()
                        );
                    }
                    "stats"
                }
                RecordMsg::ConsoleLog(_) => "console",
                RecordMsg::FileComplete { exit_code } => {
                    println!("file complete, exit={exit_code}");
                    "complete"
                }
            };
            *counts.entry(name).or_insert(0) += 1;
        }
        if !chunk.has_more || chunk.done {
            break;
        }
    }
    println!("{counts:?}");
}
