//! Subscriptions and the sampling clock they share.
//!
//! One sweep over the collectors serves every subscriber. Sweeps sit on a
//! grid spaced one base tick apart, derived from the subscribers' intervals,
//! and each subscriber is served by the first sweep at least its interval
//! after the one that last served it. Readings that describe the time since
//! the previous sweep are averaged, weighted by that time, over the sweeps a
//! subscriber sat out.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use log::{debug, warn};
use prost_types::Timestamp;
use tokio::sync::{Notify, mpsc};
use tonic::Status;

use crate::metrics::Sample;
use crate::monitors::Collectors;
use crate::record;
use crate::wandb_internal::{
    Record, StatsRecord, SubscribeRequest, SubscribeResponse, record::RecordType,
    stats_record::StatsType,
};

/// Intervals are rounded to multiples of this.
const GRANULARITY: Duration = Duration::from_millis(100);

/// A joining subscriber gets an extra sweep, but never closer than this to
/// the previous sweep, so runs starting together share a few sweeps.
const MIN_SWEEP_SPACING: Duration = Duration::from_secs(1);

/// Samples a client has not read yet. Further ones are dropped.
const QUEUE_DEPTH: usize = 4;

type Sender = mpsc::Sender<Result<SubscribeResponse, Status>>;
pub type Receiver = mpsc::Receiver<Result<SubscribeResponse, Status>>;

struct Subscription {
    interval: Duration,
    pid: u32,
    gpu_device_ids: Vec<i32>,
    tx: Sender,
    /// The scheduled time of the sweep that last served this subscriber.
    last_delivery: Option<Instant>,
    /// Weighted sum and total weight of each averaged reading since the
    /// last delivery.
    sums: HashMap<String, (f64, f64)>,
}

impl Subscription {
    /// Whether the sweep scheduled for `at` serves this subscriber.
    fn due(&self, at: Instant) -> bool {
        self.last_delivery
            .is_none_or(|last| at >= last + self.interval)
    }
}

/// The scheduled times of the previous sweeps.
#[derive(Clone, Copy)]
struct Sweeps {
    /// The last sweep on the grid.
    grid: Instant,
    /// The last sweep of any kind.
    previous: Instant,
}

/// The current subscribers.
pub struct Subscriptions {
    inner: Mutex<Vec<Subscription>>,
    /// Signaled when a subscriber joins.
    changed: Notify,
}

impl Subscriptions {
    pub fn new() -> Self {
        Self {
            inner: Mutex::new(Vec::new()),
            changed: Notify::new(),
        }
    }

    /// Adds a subscriber and returns the receiving end of its stream.
    pub fn add(&self, request: &SubscribeRequest) -> Result<Receiver, Status> {
        if !request.interval_seconds.is_finite() || request.interval_seconds <= 0.0 {
            return Err(Status::invalid_argument(
                "interval_seconds must be positive",
            ));
        }
        let ticks = (request.interval_seconds / GRANULARITY.as_secs_f64())
            .round()
            .max(1.0) as u32;

        let (tx, rx) = mpsc::channel(QUEUE_DEPTH);
        self.lock().push(Subscription {
            interval: GRANULARITY * ticks,
            pid: request.pid.max(0) as u32,
            gpu_device_ids: request.gpu_device_ids.clone(),
            tx,
            last_delivery: None,
            sums: HashMap::new(),
        });
        self.changed.notify_one();
        Ok(rx)
    }

    /// When to sweep next and whether that sweep is on the grid, or None
    /// without subscribers.
    ///
    /// Grid sweeps are one tick apart, scheduled from the previous grid
    /// sweep, or from now if that time has passed. A subscriber waiting for
    /// its first sample gets an extra sweep before the next grid sweep,
    /// MIN_SWEEP_SPACING after the previous sweep at the earliest.
    fn next_sweep(&self, last: Option<Sweeps>) -> Option<(Instant, bool)> {
        let subs = self.lock();
        if subs.is_empty() {
            return None;
        }
        let now = Instant::now();
        let Some(last) = last else {
            return Some((now, true));
        };
        let tick = base_tick(subs.iter().map(|sub| sub.interval));
        let grid = (last.grid + tick).max(now);
        if subs.iter().any(|sub| sub.last_delivery.is_none()) {
            let extra = (last.previous + MIN_SWEEP_SPACING).max(now);
            if extra < grid {
                return Some((extra, false));
            }
        }
        Some((grid, true))
    }

    /// Hands the sweep scheduled for `at` to the subscribers whose delivery
    /// is due and drops the subscribers whose clients went away.
    ///
    /// `weight` is the sweep's share of the averages, the time since the
    /// previous sweep.
    fn deliver(&self, sample: &Sample, at: Instant, weight: f64) {
        let mut subs = self.lock();
        subs.retain(|sub| !sub.tx.is_closed());

        let mut process_trees: HashMap<u32, Vec<u32>> = HashMap::new();
        for sub in subs.iter_mut() {
            for (key, value) in &sample.averages {
                let (sum, total) = sub.sums.entry(key.clone()).or_default();
                *sum += value * weight;
                *total += weight;
            }
            if !sub.due(at) {
                continue;
            }
            sub.last_delivery = Some(at);

            let averages: Vec<(String, f64)> = sub
                .sums
                .drain()
                .filter(|(_, (_, total))| *total > 0.0)
                .map(|(key, (sum, total))| (key, sum / total))
                .collect();
            let pids = process_trees
                .entry(sub.pid)
                .or_insert_with(|| record::process_tree(sub.pid));
            let items = record::stats_items(sample, &averages, pids, &sub.gpu_device_ids);
            if items.is_empty() {
                continue;
            }

            let record = Record {
                record_type: Some(RecordType::Stats(StatsRecord {
                    timestamp: Some(current_timestamp()),
                    stats_type: StatsType::System as i32,
                    item: items,
                    ..Default::default()
                })),
                ..Default::default()
            };
            let response = SubscribeResponse {
                record: Some(record),
            };
            if sub.tx.try_send(Ok(response)).is_err() {
                debug!("Subscriber is not reading its samples; dropping one");
            }
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Vec<Subscription>> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }
}

/// Sweeps the collectors on the subscribers' clock and delivers the results.
pub async fn run(subscriptions: Arc<Subscriptions>, collectors: Arc<Collectors>) {
    let mut last: Option<Sweeps> = None;
    loop {
        let Some((at, on_grid)) = subscriptions.next_sweep(last) else {
            subscriptions.changed.notified().await;
            continue;
        };
        tokio::select! {
            _ = tokio::time::sleep_until(at.into()) => {}
            _ = subscriptions.changed.notified() => continue,
        }

        let sample = sweep(&collectors).await;
        let weight = last.map_or(1.0, |last| (at - last.previous).as_secs_f64());
        subscriptions.deliver(&sample, at, weight);
        last = Some(Sweeps {
            grid: if on_grid {
                at
            } else {
                last.map_or(at, |last| last.grid)
            },
            previous: at,
        });
    }
}

/// One pass over the collectors, or an empty sample if a collector panics.
async fn sweep(collectors: &Arc<Collectors>) -> Sample {
    let collectors = collectors.clone();
    match tokio::spawn(async move { collectors.collect_metrics().await }).await {
        Ok(sample) => sample,
        Err(e) => {
            warn!("A collector panicked: {e}");
            Sample::default()
        }
    }
}

/// The clock's tick for the given intervals: their greatest common divisor,
/// unless that would sweep more than four times as often as the shortest
/// interval, in which case the shortest interval.
fn base_tick(intervals: impl Iterator<Item = Duration>) -> Duration {
    let ticks: Vec<u64> = intervals
        .map(|interval| (interval.as_millis() / GRANULARITY.as_millis()).max(1) as u64)
        .collect();
    let shortest = ticks.iter().copied().min().unwrap_or(1);
    let divisor = ticks.iter().fold(0, |a, &b| gcd(a, b));
    let tick = if divisor * 4 >= shortest {
        divisor
    } else {
        shortest
    };
    GRANULARITY * tick as u32
}

fn gcd(a: u64, b: u64) -> u64 {
    if b == 0 { a } else { gcd(b, a % b) }
}

fn current_timestamp() -> Timestamp {
    let now = chrono::Utc::now();
    Timestamp {
        seconds: now.timestamp(),
        nanos: now.timestamp_subsec_nanos() as i32,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_tick_is_the_gcd_unless_too_fine() {
        let tick = |secs: &[f64]| base_tick(secs.iter().map(|s| Duration::from_secs_f64(*s)));
        assert_eq!(tick(&[15.0]), Duration::from_secs(15));
        assert_eq!(tick(&[15.0, 10.0]), Duration::from_secs(5));
        assert_eq!(tick(&[15.0, 2.0]), Duration::from_secs(1));
        assert_eq!(tick(&[15.0, 7.0]), Duration::from_secs(7));
        assert_eq!(tick(&[0.1, 15.0]), Duration::from_millis(100));
    }

    /// The value of the one averaged metric in the next queued sample.
    fn next_average(rx: &mut Receiver) -> Option<String> {
        let response = rx.try_recv().ok()?.ok()?;
        let RecordType::Stats(stats) = response.record?.record_type? else {
            return None;
        };
        Some(stats.item.into_iter().next()?.value_json)
    }

    #[test]
    fn delivers_each_subscriber_at_its_interval_with_averages_in_between() {
        let subscriptions = Subscriptions::new();
        let subscribe = |interval_seconds| {
            subscriptions
                .add(&SubscribeRequest {
                    interval_seconds,
                    ..Default::default()
                })
                .unwrap()
        };
        let mut slow = subscribe(15.0);
        let mut fast = subscribe(5.0);

        let start = Instant::now();
        let deliver = |secs: u64, value: f64| {
            let sample = Sample {
                averages: vec![("gpu.0.smActive".to_string(), value)],
                ..Default::default()
            };
            subscriptions.deliver(&sample, start + Duration::from_secs(secs), 1.0);
        };
        deliver(0, 1.0);
        deliver(5, 2.0);
        deliver(10, 3.0);
        deliver(15, 4.0);
        deliver(18, 5.0);

        assert_eq!(next_average(&mut slow).as_deref(), Some("1.0"));
        assert_eq!(next_average(&mut slow).as_deref(), Some("3.0"));
        assert_eq!(next_average(&mut slow), None);
        for expected in ["1.0", "2.0", "3.0", "4.0"] {
            assert_eq!(next_average(&mut fast).as_deref(), Some(expected));
        }
        assert_eq!(next_average(&mut fast), None);
    }
}
