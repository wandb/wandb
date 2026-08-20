//! Port of `core/internal/leet/media.go` — media series storage for one run.

use std::cmp::Ordering;
use std::collections::HashMap;

/// MediaPoint is a single media sample logged at a particular X-axis value.
///
/// For wandb.Image v1, X is the history step. The type is intentionally generic
/// so the pane can later be extended to other X axes without changing the data
/// model.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct MediaPoint {
    pub x: f64,
    pub file_path: String,
    pub relative_path: String,
    pub caption: String,
    pub format: String,
    pub width: i64,
    pub height: i64,
    pub sha256: String,
}

/// MediaStore holds all image series for one run.
///
/// Series are keyed by the logged history key (for example
/// "media/generated_sample"). Samples within a series are ordered by X.
// PARITY: Go guards this with a sync.RWMutex; dropped — model-side state is
// accessed from the single update/view thread (docs/CONCURRENCY.md).
#[derive(Debug, Default)]
pub struct MediaStore {
    series: HashMap<String, Vec<MediaPoint>>,
    keys: Vec<String>,
    x_values: Vec<f64>,
}

impl MediaStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// ProcessHistory ingests media payloads from a history message.
    ///
    /// Returns true when the store changed.
    // PARITY: Go takes the whole HistoryMsg (messages.go → leet-tui) and reads
    // only msg.Media; the store takes the media payload directly so leet-data
    // stays free of TUI message types. Callers pass `&msg.media`.
    pub fn process_history(&mut self, media: &HashMap<String, Vec<MediaPoint>>) -> bool {
        if media.is_empty() {
            return false;
        }

        let mut changed = false;
        // PARITY: Go map iteration order is random; the resulting store state
        // is order-independent (sorted key list, sorted per-series inserts).
        for (key, points) in media {
            if key.is_empty() || points.is_empty() {
                continue;
            }

            if !self.series.contains_key(key) {
                self.keys.push(key.clone());
                // PARITY: Go slices.SortFunc is unstable; keys are unique, so
                // stability is unobservable.
                self.keys.sort_unstable_by(|a, b| compare_natural(a, b));
                changed = true;
            }

            // PARITY: Go reads the slice out of the map, mutates a local, and
            // writes it back; mirrored with remove/insert.
            let mut series = self.series.remove(key).unwrap_or_default();
            for point in points {
                let point_changed = upsert_media_point(&mut series, point.clone());
                if point_changed {
                    self.append_x_value_locked(point.x);
                    changed = true;
                }
            }
            self.series.insert(key.clone(), series);
        }

        changed
    }

    // PARITY: "Locked" suffix kept from Go for grep-ability; the lock itself
    // is gone (see MediaStore).
    fn append_x_value_locked(&mut self, x: f64) {
        if self.x_values.is_empty() || x > self.x_values[self.x_values.len() - 1] {
            self.x_values.push(x);
            return;
        }

        let (idx, found) = slices_binary_search_f64(&self.x_values, x);
        if found {
            return;
        }

        self.x_values.insert(idx, x);
    }

    /// SeriesKeys returns the sorted set of media series keys.
    pub fn series_keys(&self) -> Vec<String> {
        self.keys.clone()
    }

    /// XValues returns the sorted union of X-axis values across all media series.
    pub fn x_values(&self) -> Vec<f64> {
        self.x_values.clone()
    }

    /// SeriesXValues returns the sorted X-axis values for a single series.
    pub fn series_x_values(&self, key: &str) -> Vec<f64> {
        // PARITY: Go returns nil for an unknown/empty series; callers only
        // check len and index, so an empty Vec is equivalent.
        match self.series.get(key) {
            Some(series) => series.iter().map(|p| p.x).collect(),
            None => Vec::new(),
        }
    }

    /// ResolveAt returns the most recent media sample for key whose X <= x.
    pub fn resolve_at(&self, key: &str, x: f64) -> Option<MediaPoint> {
        let series = self.series.get(key)?;
        if series.is_empty() {
            return None;
        }

        let idx = sort_search(series.len(), |i| series[i].x > x);
        if idx == 0 {
            return None;
        }
        Some(series[idx - 1].clone())
    }

    /// Empty reports whether the store contains any media series.
    pub fn empty(&self) -> bool {
        self.keys.is_empty()
    }
}

fn upsert_media_point(series: &mut Vec<MediaPoint>, point: MediaPoint) -> bool {
    // First index whose X is strictly greater than point.X.
    let idx = sort_search(series.len(), |i| series[i].x > point.x);

    // Last writer wins at a given X.
    if idx > 0 && series[idx - 1].x == point.x {
        if series[idx - 1] == point {
            return false;
        }
        series[idx - 1] = point;
        return true;
    }

    // PARITY: Go grows by one and copy-shifts; Vec::insert is identical.
    series.insert(idx, point);
    true
}

/// PARITY: Go sort.Search — the smallest index in [0, n) at which f(i) is
/// true, assuming f is false for a prefix and true for the rest; returns n if
/// f is always false. Rust's partition_point takes the inverted predicate and
/// diverges from Go when the predicate involves NaN comparisons, so the Go
/// loop is ported verbatim.
fn sort_search(n: usize, mut f: impl FnMut(usize) -> bool) -> usize {
    let (mut i, mut j) = (0, n);
    while i < j {
        let h = (i + j) >> 1; // Go: int(uint(i+j) >> 1)
        if !f(h) {
            i = h + 1;
        } else {
            j = h;
        }
    }
    i
}

/// PARITY: Go slices.BinarySearch on []float64 — smallest index i at which
/// !cmp.Less(xs[i], target), plus whether target was found there. cmp.Less
/// orders NaN before every other value (x < y || (isNaN(x) && !isNaN(y))),
/// which no std binary search reproduces, so it is ported verbatim.
fn slices_binary_search_f64(xs: &[f64], target: f64) -> (usize, bool) {
    fn cmp_less(x: f64, y: f64) -> bool {
        x < y || (x.is_nan() && !y.is_nan())
    }

    let n = xs.len();
    let (mut i, mut j) = (0, n);
    while i < j {
        let h = (i + j) >> 1;
        if cmp_less(xs[h], target) {
            i = h + 1;
        } else {
            j = h;
        }
    }
    let found = i < n && (xs[i] == target || (xs[i].is_nan() && target.is_nan()));
    (i, found)
}

/// compareNatural orders strings lexicographically, except that runs of ASCII
/// digits compare numerically, so "key[2]" sorts before "key[10]".
fn compare_natural(a: &str, b: &str) -> Ordering {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    let (mut i, mut j) = (0, 0);
    while i < a.len() && j < b.len() {
        if a[i].is_ascii_digit() && b[j].is_ascii_digit() {
            let (mut a_end, mut b_end) = (i, j);
            while a_end < a.len() && a[a_end].is_ascii_digit() {
                a_end += 1;
            }
            while b_end < b.len() && b[b_end].is_ascii_digit() {
                b_end += 1;
            }
            let a_num = trim_left_zeros(&a[i..a_end]);
            let b_num = trim_left_zeros(&b[j..b_end]);
            let c = a_num.len().cmp(&b_num.len());
            if c != Ordering::Equal {
                return c;
            }
            let c = a_num.cmp(b_num);
            if c != Ordering::Equal {
                return c;
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

/// Go: strings.TrimLeft(s, "0").
fn trim_left_zeros(mut s: &[u8]) -> &[u8] {
    while let Some((b'0', rest)) = s.split_first() {
        s = rest;
    }
    s
}

/// resolveMediaPath resolves a media file path from a history record to the file
/// on disk for the given run.
///
/// Go-unexported; pub here for the leveldb history source port and the
/// unit-diff harness (PARITY.md MED-01).
pub fn resolve_media_path(run_path: &str, relative_path: &str) -> String {
    if relative_path.is_empty() {
        return String::new();
    }
    if is_abs(relative_path) {
        return clean_path(relative_path);
    }

    // Go: filepath.Clean(string(filepath.Separator) + relativePath), then
    // strings.TrimPrefix(clean, string(filepath.Separator)).
    let clean = clean_path(&format!("/{relative_path}"));
    let clean = clean.strip_prefix('/').unwrap_or(&clean);

    join_paths(&[&dir_path(run_path), "files", clean])
}

// PARITY: Go filepath is platform-dependent; leet's paths are '/'-separated on
// its supported targets, so the unix (path.Clean/Dir/Join) semantics are
// ported. std::path has no lexical Clean, hence the verbatim ports below.

/// Go (unix): filepath.IsAbs.
fn is_abs(path: &str) -> bool {
    path.starts_with('/')
}

/// Go (unix): filepath.Dir — everything up to the final separator, cleaned;
/// "." when the path contains no separator.
fn dir_path(path: &str) -> String {
    match path.rfind('/') {
        Some(i) => clean_path(&path[..=i]),
        None => clean_path(""),
    }
}

/// Go (unix): filepath.Join — join the first non-empty element onward with
/// '/' and Clean the result; "" when all elements are empty.
fn join_paths(elem: &[&str]) -> String {
    for (i, e) in elem.iter().enumerate() {
        if !e.is_empty() {
            return clean_path(&elem[i..].join("/"));
        }
    }
    String::new()
}

/// Go (unix): filepath.Clean — shortest lexically-equivalent path. Ported
/// verbatim from Go's path.Clean (BSD-licensed Go stdlib, path/path.go).
fn clean_path(path: &str) -> String {
    let p = path.as_bytes();
    if p.is_empty() {
        return ".".to_string();
    }

    let rooted = p[0] == b'/';
    let n = p.len();

    // Invariants (from Go):
    //	reading from path; r is index of next byte to process.
    //	writing to out; out.len() is index of next byte to write.
    //	dotdot is index in out where .. must stop, either because
    //		it is the leading slash or it is a leading ../../.. prefix.
    let mut out: Vec<u8> = Vec::with_capacity(n);
    let mut r = 0usize;
    let mut dotdot = 0usize;
    if rooted {
        out.push(b'/');
        r = 1;
        dotdot = 1;
    }

    while r < n {
        if p[r] == b'/' {
            // empty path element
            r += 1;
        } else if p[r] == b'.' && (r + 1 == n || p[r + 1] == b'/') {
            // . element
            r += 1;
        } else if p[r] == b'.' && p[r + 1] == b'.' && (r + 2 == n || p[r + 2] == b'/') {
            // .. element: remove to last /
            r += 2;
            if out.len() > dotdot {
                // can backtrack
                let mut w = out.len() - 1; // Go: out.w--
                while w > dotdot && out[w] != b'/' {
                    w -= 1;
                }
                out.truncate(w);
            } else if !rooted {
                // cannot backtrack, but not rooted, so append .. element.
                if !out.is_empty() {
                    out.push(b'/');
                }
                out.push(b'.');
                out.push(b'.');
                dotdot = out.len();
            }
        } else {
            // real path element.
            // add slash if needed
            if (rooted && out.len() != 1) || (!rooted && !out.is_empty()) {
                out.push(b'/');
            }
            // copy element
            while r < n && p[r] != b'/' {
                out.push(p[r]);
                r += 1;
            }
        }
    }

    // Turn empty string into "."
    if out.is_empty() {
        return ".".to_string();
    }
    String::from_utf8(out).expect("clean_path copies whole UTF-8 segments")
}

// PARITY: DEFERRED TESTS — media_test.go contains four TestParseHistory_*
// cases exercising ParseHistory, which lives in leveldbhistorysource.go and is
// ported by the leveldb_history_source unit. That unit MUST transliterate all
// four in addition to leveldbhistorysource_test.go's own cases:
//   - TestParseHistory_ImageFile
//   - TestParseHistory_ImageFile_NormalizesRelativePathWithinFilesDir
//   - TestParseHistory_ImagesSeparated (per-image fan-out into "key[i]" series,
//     caption index alignment, and "attention_maps.count" must NOT leak into
//     scalar Metrics)
//   - TestParseHistory_ImagesSeparated_NoCaptions
// The resolveMediaPath expectations embedded in the first two are covered
// below; the rest of their behavior is not testable from this module.
#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use pretty_assertions::assert_eq;

    use super::*;

    fn media_map(key: &str, points: Vec<MediaPoint>) -> HashMap<String, Vec<MediaPoint>> {
        HashMap::from([(key.to_string(), points)])
    }

    // Go: TestMediaStoreSeriesKeys_NaturalOrder.
    #[test]
    fn media_store_series_keys_natural_order() {
        let mut store = MediaStore::new();
        for key in ["maps[10]", "maps[2]", "maps[0]", "loss", "zmap"] {
            store.process_history(&media_map(
                key,
                vec![MediaPoint {
                    x: 1.0,
                    file_path: "/img.png".to_string(),
                    ..Default::default()
                }],
            ));
        }
        assert_eq!(
            store.series_keys(),
            vec!["loss", "maps[0]", "maps[2]", "maps[10]", "zmap"],
        );
    }

    // Go: TestMediaStoreResolveAt.
    #[test]
    fn media_store_resolve_at() {
        let mut store = MediaStore::new();

        assert!(store.process_history(&media_map(
            "media/generated_sample",
            vec![MediaPoint {
                x: 1.0,
                file_path: "/tmp/1.png".to_string(),
                caption: "step=1".to_string(),
                ..Default::default()
            }],
        )));
        assert!(store.process_history(&media_map(
            "media/generated_sample",
            vec![MediaPoint {
                x: 5.0,
                file_path: "/tmp/5.png".to_string(),
                caption: "step=5".to_string(),
                ..Default::default()
            }],
        )));

        let point = store.resolve_at("media/generated_sample", 4.0).unwrap();
        assert_eq!(point.file_path, "/tmp/1.png");
        assert_eq!(point.caption, "step=1");

        let point = store.resolve_at("media/generated_sample", 5.0).unwrap();
        assert_eq!(point.file_path, "/tmp/5.png");
        assert_eq!(point.caption, "step=5");

        assert!(store.resolve_at("media/generated_sample", 0.0).is_none());
    }

    // Go: TestMediaStoreProcessHistory_ReplacesExistingPointAtSameX.
    #[test]
    fn media_store_process_history_replaces_existing_point_at_same_x() {
        let mut store = MediaStore::new();

        assert!(store.process_history(&media_map(
            "media/generated_sample",
            vec![MediaPoint {
                x: 5.0,
                file_path: join_paths(&["tmp", "old.png"]),
                caption: "old".to_string(),
                ..Default::default()
            }],
        )));

        assert!(store.process_history(&media_map(
            "media/generated_sample",
            vec![MediaPoint {
                x: 5.0,
                file_path: join_paths(&["tmp", "new.png"]),
                caption: "new".to_string(),
                ..Default::default()
            }],
        )));

        let point = store.resolve_at("media/generated_sample", 5.0).unwrap();
        assert_eq!(point.file_path, join_paths(&["tmp", "new.png"]));
        assert_eq!(point.caption, "new");
        assert_eq!(store.series_x_values("media/generated_sample"), vec![5.0]);
    }

    // Go: the resolveMediaPath expectation inside TestParseHistory_ImageFile.
    // The ParseHistory transliteration itself belongs to the
    // leveldb_history_source unit.
    #[test]
    fn resolve_media_path_image_file() {
        let run_path = "tmp/offline-run-123/run-123.wandb";
        let rel_path = "media/images/media/generated_sample_7.png";
        assert_eq!(
            resolve_media_path(run_path, rel_path),
            "tmp/offline-run-123/files/media/images/media/generated_sample_7.png",
        );
    }

    // Go: the resolveMediaPath expectation inside
    // TestParseHistory_ImageFile_NormalizesRelativePathWithinFilesDir.
    #[test]
    fn resolve_media_path_normalizes_relative_path_within_files_dir() {
        let run_path = "tmp/offline-run-123/run-123.wandb";
        let rel_path = "../outside/generated_sample_7.png";
        assert_eq!(
            resolve_media_path(run_path, rel_path),
            "tmp/offline-run-123/files/outside/generated_sample_7.png",
        );
    }

    // Port-added coverage (no Go counterpart): the remaining resolveMediaPath
    // branches — empty relative path and absolute pass-through with Clean.
    #[test]
    fn resolve_media_path_empty_and_absolute() {
        assert_eq!(resolve_media_path("tmp/run/run.wandb", ""), "");
        assert_eq!(
            resolve_media_path("tmp/run/run.wandb", "/abs/dir/../img.png"),
            "/abs/img.png",
        );
    }

    // Port-added coverage (no Go counterpart): xValues stays the sorted,
    // deduped union across series even when steps arrive out of order.
    #[test]
    fn media_store_x_values_sorted_union() {
        let mut store = MediaStore::new();
        store.process_history(&media_map(
            "a",
            vec![
                MediaPoint {
                    x: 5.0,
                    file_path: "/a5.png".to_string(),
                    ..Default::default()
                },
                MediaPoint {
                    x: 1.0,
                    file_path: "/a1.png".to_string(),
                    ..Default::default()
                },
            ],
        ));
        store.process_history(&media_map(
            "b",
            vec![
                MediaPoint {
                    x: 3.0,
                    file_path: "/b3.png".to_string(),
                    ..Default::default()
                },
                MediaPoint {
                    x: 5.0,
                    file_path: "/b5.png".to_string(),
                    ..Default::default()
                },
            ],
        ));
        assert_eq!(store.x_values(), vec![1.0, 3.0, 5.0]);
        assert_eq!(store.series_x_values("a"), vec![1.0, 5.0]);
        assert_eq!(store.series_x_values("b"), vec![3.0, 5.0]);
    }

    // Port-added coverage (no Go counterpart): re-ingesting an identical point
    // reports no change; empty keys and empty point lists are skipped.
    #[test]
    fn media_store_process_history_no_change_paths() {
        let mut store = MediaStore::new();
        assert!(store.empty());

        assert!(!store.process_history(&HashMap::new()));
        assert!(!store.process_history(&media_map("", vec![MediaPoint::default()])));
        assert!(!store.process_history(&media_map("k", vec![])));
        assert!(store.empty());

        let point = MediaPoint {
            x: 2.0,
            file_path: "/2.png".to_string(),
            ..Default::default()
        };
        assert!(store.process_history(&media_map("k", vec![point.clone()])));
        assert!(!store.process_history(&media_map("k", vec![point])));
        assert!(!store.empty());
    }
}
