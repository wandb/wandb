//! Media series storage for one run.

use std::collections::HashMap;

use crate::msg::{HistoryMsg, MediaPoint};

/// Holds all image series for one run.
///
/// Series are keyed by the logged history key (for example
/// "media/generated_sample"). Samples within a series are ordered by X.
#[derive(Default)]
pub struct MediaStore {
    series: HashMap<String, Vec<MediaPoint>>,
    keys: Vec<String>,
    x_values: Vec<f64>,
}

impl MediaStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// Ingests media payloads from a history message.
    ///
    /// Returns true when the store changed.
    pub fn process_history(&mut self, msg: &HistoryMsg) -> bool {
        let mut changed = false;
        for (key, points) in &msg.media {
            if key.is_empty() || points.is_empty() {
                continue;
            }

            if !self.series.contains_key(key) {
                self.series.insert(key.clone(), Vec::new());
                self.keys.push(key.clone());
                self.keys.sort_by(|a, b| compare_natural(a, b));
                changed = true;
            }

            let series = self.series.get_mut(key).expect("just inserted");
            for point in points {
                if upsert_media_point(series, point) {
                    append_x_value(&mut self.x_values, point.x);
                    changed = true;
                }
            }
        }
        changed
    }

    /// The sorted set of media series keys.
    pub fn series_keys(&self) -> &[String] {
        &self.keys
    }

    /// The sorted union of X-axis values across all media series.
    pub fn x_values(&self) -> &[f64] {
        &self.x_values
    }

    /// The sorted X-axis values for a single series.
    pub fn series_x_values(&self, key: &str) -> Vec<f64> {
        self.series
            .get(key)
            .map(|s| s.iter().map(|p| p.x).collect())
            .unwrap_or_default()
    }

    /// The most recent media sample for `key` whose X <= `x`.
    pub fn resolve_at(&self, key: &str, x: f64) -> Option<&MediaPoint> {
        let series = self.series.get(key)?;
        let idx = series.partition_point(|p| p.x <= x);
        if idx == 0 {
            return None;
        }
        series.get(idx - 1)
    }

    /// Whether the store contains any media series.
    pub fn is_empty(&self) -> bool {
        self.keys.is_empty()
    }
}

/// Inserts or replaces (last writer wins) a point at its X position.
/// Returns true when the series changed.
fn upsert_media_point(series: &mut Vec<MediaPoint>, point: &MediaPoint) -> bool {
    let idx = series.partition_point(|p| p.x <= point.x);

    if idx > 0 && series[idx - 1].x == point.x {
        if series[idx - 1] == *point {
            return false;
        }
        series[idx - 1] = point.clone();
        return true;
    }

    series.insert(idx, point.clone());
    true
}

fn append_x_value(xs: &mut Vec<f64>, x: f64) {
    if xs.last().is_none_or(|&last| x > last) {
        xs.push(x);
        return;
    }
    let idx = xs.partition_point(|&v| v < x);
    if xs.get(idx) == Some(&x) {
        return;
    }
    xs.insert(idx, x);
}

/// Orders strings lexicographically, except that runs of ASCII digits
/// compare numerically, so "key[2]" sorts before "key[10]".
pub fn compare_natural(a: &str, b: &str) -> std::cmp::Ordering {
    use std::cmp::Ordering;

    let a = a.as_bytes();
    let b = b.as_bytes();
    let (mut i, mut j) = (0, 0);

    while i < a.len() && j < b.len() {
        if a[i].is_ascii_digit() && b[j].is_ascii_digit() {
            let mut a_end = i;
            while a_end < a.len() && a[a_end].is_ascii_digit() {
                a_end += 1;
            }
            let mut b_end = j;
            while b_end < b.len() && b[b_end].is_ascii_digit() {
                b_end += 1;
            }
            let a_num = &a[i..a_end];
            let b_num = &b[j..b_end];
            let a_num = &a_num[a_num.iter().take_while(|&&c| c == b'0').count()..];
            let b_num = &b_num[b_num.iter().take_while(|&&c| c == b'0').count()..];
            match a_num.len().cmp(&b_num.len()) {
                Ordering::Equal => {}
                ord => return ord,
            }
            match a_num.cmp(b_num) {
                Ordering::Equal => {}
                ord => return ord,
            }
            i = a_end;
            j = b_end;
            continue;
        }
        if a[i] != b[j] {
            return a[i].cmp(&b[j]);
        }
        i += 1;
        j += 1;
    }
    (a.len() - i).cmp(&(b.len() - j))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn natural_ordering() {
        use std::cmp::Ordering::*;
        assert_eq!(compare_natural("key[2]", "key[10]"), Less);
        assert_eq!(compare_natural("a", "b"), Less);
        assert_eq!(compare_natural("a10", "a10"), Equal);
        assert_eq!(compare_natural("a02", "a2"), Equal);
    }

    #[test]
    fn store_resolves_latest_at_or_before_x() {
        let mut store = MediaStore::new();
        let msg = HistoryMsg {
            media: vec![(
                "img".to_string(),
                vec![
                    MediaPoint {
                        x: 10.0,
                        file_path: "a.png".into(),
                        ..Default::default()
                    },
                    MediaPoint {
                        x: 20.0,
                        file_path: "b.png".into(),
                        ..Default::default()
                    },
                ],
            )],
            ..Default::default()
        };
        assert!(store.process_history(&msg));
        assert!(!store.process_history(&msg)); // idempotent

        assert!(store.resolve_at("img", 5.0).is_none());
        assert_eq!(store.resolve_at("img", 15.0).unwrap().file_path, "a.png");
        assert_eq!(store.resolve_at("img", 20.0).unwrap().file_path, "b.png");
        assert_eq!(store.x_values(), &[10.0, 20.0]);
    }
}
