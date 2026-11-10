//! Subscriptions and the sampling clock they share.
//!
//! One sweep over the collectors serves every subscriber. Sweeps sit on a
//! grid spaced one base tick apart, derived from the subscribers' intervals,
//! and each subscriber is served by the first sweep at least its interval
//! after the one that last served it. Readings that describe the time since
//! the previous sweep are averaged, weighted by that time, over the sweeps a
//! subscriber sat out. Counters are reported as their increase since the
//! subscriber's first sample.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use log::debug;
use prost_types::Timestamp;
use tokio::sync::{Notify, mpsc};
use tonic::Status;

use crate::metrics::{Field, Sample, Scope};
use crate::monitors::Collectors;
use crate::record;
use crate::wandb_internal::{SubscribeRequest, SubscribeResponse, SystemMetricsRecord};

/// Intervals are rounded to multiples of this.
const GRANULARITY: Duration = Duration::from_millis(100);

/// A joining subscriber gets an extra sweep, but never closer than this to
/// the previous sweep, so runs starting together share a few sweeps.
const MIN_SWEEP_SPACING: Duration = Duration::from_secs(1);

/// Samples a client has not read yet. Further ones are dropped.
const QUEUE_DEPTH: usize = 4;

/// How long a subscriber's counter baselines outlive its stream, so that a
/// stream reopened under the same ID keeps counting.
const BASELINE_RETENTION: Duration = Duration::from_secs(10 * 60);

type Sender = mpsc::Sender<Result<SubscribeResponse, Status>>;
pub type Receiver = mpsc::Receiver<Result<SubscribeResponse, Status>>;

struct Subscription {
    interval: Duration,
    gpu_device_ids: Vec<i32>,
    scope: Scope,
    baseline: BaselineKey,
    tx: Sender,
    /// The scheduled time of the sweep that last served this subscriber.
    last_delivery: Option<Instant>,
    /// Weighted sum and total weight of each averaged reading since the
    /// last delivery.
    sums: HashMap<Field, (f64, f64)>,
    /// Samples dropped since the last one delivered.
    dropped: u32,
}

impl Subscription {
    /// Whether the sweep scheduled for `at` serves this subscriber.
    fn due(&self, at: Instant) -> bool {
        self.last_delivery
            .is_none_or(|last| at >= last + self.interval)
    }
}

/// Who a set of counter baselines belongs to: the client's subscriber ID,
/// or the stream itself when the client gave none.
#[derive(Clone, PartialEq, Eq, Hash)]
enum BaselineKey {
    Id(String),
    Stream(u64),
}

/// The first value of each counter a subscriber saw.
#[derive(Default)]
struct Baseline {
    counters: HashMap<Field, f64>,
    /// When the subscriber's last stream closed, if it is not live.
    closed: Option<Instant>,
}

/// The scheduled times of the previous sweeps.
#[derive(Clone, Copy)]
struct Sweeps {
    /// The last sweep on the grid.
    grid: Instant,
    /// The last sweep of any kind.
    previous: Instant,
}

#[derive(Default)]
struct State {
    subs: Vec<Subscription>,
    baselines: HashMap<BaselineKey, Baseline>,
    /// Streams opened so far, numbering those without a subscriber ID.
    streams: u64,
}

/// The current subscribers.
pub struct Subscriptions {
    inner: Mutex<State>,
    /// Signaled when a subscriber joins.
    changed: Notify,
}

impl Subscriptions {
    pub fn new() -> Self {
        Self {
            inner: Mutex::new(State::default()),
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
        let mut state = self.lock();
        state.streams += 1;
        let baseline = if request.subscriber_id.is_empty() {
            BaselineKey::Stream(state.streams)
        } else {
            BaselineKey::Id(request.subscriber_id.clone())
        };
        state.subs.push(Subscription {
            interval: GRANULARITY * ticks,
            gpu_device_ids: request.gpu_device_ids.clone(),
            scope: Scope::from(request),
            baseline,
            tx,
            last_delivery: None,
            sums: HashMap::new(),
            dropped: 0,
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
        let state = self.lock();
        let subs = &state.subs;
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

    /// The distinct scopes of the current subscribers.
    fn scopes(&self) -> Vec<Scope> {
        let mut scopes: Vec<Scope> = Vec::new();
        for sub in &self.lock().subs {
            if !scopes.contains(&sub.scope) {
                scopes.push(sub.scope.clone());
            }
        }
        scopes
    }

    /// Hands the sweep scheduled for `at` to the subscribers whose delivery
    /// is due and drops the subscribers whose clients went away.
    ///
    /// `weight` is the sweep's share of the averages, the time since the
    /// previous sweep.
    fn deliver(&self, sample: &Sample, at: Instant, weight: f64) {
        let now = Instant::now();
        let mut state = self.lock();
        let State {
            subs, baselines, ..
        } = &mut *state;
        subs.retain(|sub| !sub.tx.is_closed());
        baselines.retain(|_, baseline| {
            baseline
                .closed
                .is_none_or(|closed| now < closed + BASELINE_RETENTION)
        });
        for (key, baseline) in baselines.iter_mut() {
            if subs.iter().any(|sub| sub.baseline == *key) {
                baseline.closed = None;
            } else {
                baseline.closed.get_or_insert(now);
            }
        }

        let timestamp = wall_clock_time(at);
        for sub in subs.iter_mut() {
            let scoped = sample.scoped.get(&sub.scope);
            if scoped.is_none() && !sample.scoped.is_empty() {
                continue;
            }
            let averages = sample
                .averages
                .iter()
                .chain(scoped.into_iter().flat_map(|readings| &readings.averages));
            for (key, value) in averages {
                let (sum, total) = sub.sums.entry(key.clone()).or_default();
                *sum += value * weight;
                *total += weight;
            }
            if !sub.due(at) {
                continue;
            }
            let since_last = sub.last_delivery.map_or(Duration::ZERO, |last| at - last);
            sub.last_delivery = Some(at);

            let mut values: Vec<(Field, f64)> = sub
                .sums
                .drain()
                .filter(|(_, (_, total))| *total > 0.0)
                .map(|(key, (sum, total))| (key, sum / total))
                .collect();
            let baseline = baselines.entry(sub.baseline.clone()).or_default();
            let counters = sample
                .counters
                .iter()
                .chain(scoped.into_iter().flat_map(|readings| &readings.counters));
            for (key, value) in counters {
                let base = baseline.counters.entry(key.clone()).or_insert(*value);
                *base = base.min(*value);
                values.push((key.clone(), value - *base));
            }
            let pids = match scoped {
                Some(readings) if !readings.pids.is_empty() => readings.pids.as_slice(),
                _ => std::slice::from_ref(&sub.scope.pid),
            };
            let mut typed =
                record::typed_record(sample, scoped, &values, pids, &sub.gpu_device_ids);
            if typed == SystemMetricsRecord::default() {
                continue;
            }
            typed.timestamp = Some(timestamp);
            typed.interval_ms = since_last.as_millis() as u32;
            typed.dropped_samples = sub.dropped;
            let response = SubscribeResponse {
                record: None,
                sample: Some(typed),
                processes: if sub.scope.host_details {
                    sample.processes.clone()
                } else {
                    Vec::new()
                },
            };
            if sub.tx.try_send(Ok(response)).is_err() {
                debug!("Subscriber is not reading its samples; dropping one");
                sub.dropped += 1;
            } else {
                sub.dropped = 0;
            }
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, State> {
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

        let sample = collectors.collect_metrics(subscriptions.scopes()).await;
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

/// The wall-clock time of the sweep scheduled for `at`.
///
/// Samples carry it instead of the time their collection finished, so a
/// subscriber's samples are exactly its interval apart however long the
/// collectors take.
fn wall_clock_time(at: Instant) -> Timestamp {
    let time = chrono::Utc::now() - Instant::now().saturating_duration_since(at);
    Timestamp {
        seconds: time.timestamp(),
        nanos: time.timestamp_subsec_nanos() as i32,
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

    /// The network bytes sent in the next queued sample.
    fn next_value(rx: &mut Receiver) -> Option<u64> {
        let sample = rx.try_recv().ok()?.ok()?.sample?;
        sample.host?.network?.sent_bytes
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
                averages: vec![(Field::NetworkSent, value)],
                ..Default::default()
            };
            subscriptions.deliver(&sample, start + Duration::from_secs(secs), 1.0);
        };
        deliver(0, 1.0);
        deliver(5, 2.0);
        deliver(10, 3.0);
        deliver(15, 4.0);
        deliver(18, 5.0);

        assert_eq!(next_value(&mut slow), Some(1));
        assert_eq!(next_value(&mut slow), Some(3));
        assert_eq!(next_value(&mut slow), None);
        for expected in [1, 2, 3, 4] {
            assert_eq!(next_value(&mut fast), Some(expected));
        }
        assert_eq!(next_value(&mut fast), None);
    }

    #[test]
    fn samples_carry_the_scheduled_time_and_the_time_since_the_previous_one() {
        let subscriptions = Subscriptions::new();
        let mut rx = subscriptions
            .add(&SubscribeRequest {
                interval_seconds: 15.0,
                ..Default::default()
            })
            .unwrap();
        let start = Instant::now() - Duration::from_secs(60);
        for secs in [0, 15, 32] {
            let sample = Sample {
                averages: vec![(Field::NetworkSent, 1.0)],
                ..Default::default()
            };
            subscriptions.deliver(&sample, start + Duration::from_secs(secs), 1.0);
        }

        let samples: Vec<SystemMetricsRecord> =
            std::iter::from_fn(|| rx.try_recv().ok()?.ok()?.sample).collect();
        let intervals: Vec<u32> = samples.iter().map(|sample| sample.interval_ms).collect();
        assert_eq!(intervals, [0, 15_000, 17_000]);
        let seconds = |sample: &SystemMetricsRecord| {
            let time = sample.timestamp.expect("no timestamp");
            time.seconds as f64 + f64::from(time.nanos) / 1e9
        };
        let elapsed = seconds(&samples[2]) - seconds(&samples[0]);
        assert!((elapsed - 32.0).abs() < 0.5, "{elapsed}");
    }

    #[test]
    fn counters_count_from_the_first_sample_and_survive_a_reopened_stream() {
        let subscriptions = Subscriptions::new();
        let subscribe = || {
            subscriptions
                .add(&SubscribeRequest {
                    interval_seconds: 1.0,
                    subscriber_id: "run".to_string(),
                    ..Default::default()
                })
                .unwrap()
        };
        let start = Instant::now();
        let deliver = |secs: u64, value: f64| {
            let sample = Sample {
                counters: vec![(Field::NetworkSent, value)],
                ..Default::default()
            };
            subscriptions.deliver(&sample, start + Duration::from_secs(secs), 1.0);
        };

        let mut first = subscribe();
        deliver(0, 100.0);
        deliver(1, 150.0);
        assert_eq!(next_value(&mut first), Some(0));
        assert_eq!(next_value(&mut first), Some(50));

        drop(first);
        let mut second = subscribe();
        deliver(2, 160.0);
        assert_eq!(next_value(&mut second), Some(60));
    }
}
