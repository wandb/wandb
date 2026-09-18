//! Port of `core/internal/runconfig` — the subset used by
//! `core/internal/leet/runoverview.go` (`New`, `NewFrom`, `ApplyChangeRecord`,
//! `CloneTree`).
//!
//! Also hosts the used subsets of runconfig's two data dependencies, shared
//! with [`crate::run_summary`]:
//!
//! - `core/internal/pathtree` ([`TreePath`], [`PathTree`], [`set_subtree`]);
//! - `github.com/wandb/simplejsonext` ([`unmarshal_string`]) — JSON extended
//!   with `NaN` / `Infinity` / `-Infinity` literals, decoding numbers as
//!   int64 when integral and in-range, float64 otherwise.
//!
//! Values are held as `serde_json::Value` (the Go code holds `any` produced
//! by simplejsonext: int64, float64, string, bool, nil, []any,
//! map[string]any).
//
// PARITY: serde_json::Number cannot represent NaN/±Inf. simplejsonext parses
// those literals into float64; here they are stored as their Go
// `fmt.Sprint` renderings ("NaN", "+Inf", "-Inf"). Every value this unit
// surfaces goes through RunOverview's fmt.Sprint port, so the on-screen
// strings are identical; only the in-tree type differs (string vs float64).

use std::collections::HashMap;

use leet_proto::wandb_internal::{ConfigItem, ConfigRecord};
use serde_json::{Map, Value};

// --- pathtree (used subset) -------------------------------------------------

/// TreePath is the list of node labels along the path from the root
/// of a PathTree to a node.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TreePath {
    /// A non-empty list defining the path.
    labels: Vec<String>,
}

impl TreePath {
    /// PathOf creates a TreePath from a list of labels.
    pub fn path_of(first: &str, rest: &[&str]) -> TreePath {
        let mut labels = Vec::with_capacity(1 + rest.len());
        labels.push(first.to_string());
        labels.extend(rest.iter().map(|s| s.to_string()));
        TreePath { labels }
    }

    /// Creates a TreePath from an owned, non-empty label list.
    ///
    /// Convenience over Go's `PathOf(key[0], key[1:]...)` splat for callers
    /// holding a `Vec<String>` (the proto `nested_key` fields).
    pub fn from_labels(labels: Vec<String>) -> TreePath {
        debug_assert!(!labels.is_empty(), "TreePath labels must be non-empty");
        TreePath { labels }
    }

    /// PathWithPrefix creates a TreePath from a prefix and an end label.
    pub fn path_with_prefix(prefix: &[String], key: &str) -> TreePath {
        let mut labels = Vec::with_capacity(prefix.len() + 1);
        labels.extend(prefix.iter().cloned());
        labels.push(key.to_string());
        TreePath { labels }
    }

    /// With returns a TreePath extended by the additional label.
    // PARITY: Go's variadic With(more ...string); only the single-label form
    // is used (pathtree.SetSubtree).
    pub fn with(&self, more: &str) -> TreePath {
        let mut labels = Vec::with_capacity(self.labels.len() + 1);
        labels.extend(self.labels.iter().cloned());
        labels.push(more.to_string());
        TreePath { labels }
    }

    /// Parent returns this path without the last component.
    ///
    /// Returns `None` if the path has no parent.
    pub fn parent(&self) -> Option<TreePath> {
        if self.labels.len() <= 1 {
            return None;
        }
        Some(TreePath {
            labels: self.labels[..self.labels.len() - 1].to_vec(),
        })
    }

    /// Labels returns the path as a list of labels.
    pub fn labels(&self) -> &[String] {
        &self.labels
    }

    /// Prefix returns all but the last label in the path.
    pub fn prefix(&self) -> &[String] {
        &self.labels[..self.labels.len() - 1]
    }

    /// End returns the last label in the path.
    pub fn end(&self) -> &str {
        &self.labels[self.labels.len() - 1]
    }
}

/// Internal representation for a nested key-value pair.
// PARITY: Go's treeData is an unordered map — a HashMap like Go (O(1) ops on
// the summary-ingest hot path; a BTreeMap here measured ~55% slower on a
// 287MB run's 5M summary items). Iteration order is unobservable: see the
// [`PathTree::for_each_leaf`] note, and [`to_nested_maps`] feeds
// `serde_json::Map`, which sorts its keys.
pub(crate) type TreeData<T> = HashMap<String, TreeNode<T>>;

/// A node is either a leaf value or a subtree.
// PARITY: Go's treeNode is a struct where `Subtree == nil` means leaf (even
// if the leaf value itself is nil); an enum encodes the same distinction.
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum TreeNode<T> {
    Leaf(T),
    Subtree(TreeData<T>),
}

impl<T> TreeNode<T> {
    /// IsLeaf reports whether the node is a leaf.
    fn is_leaf(&self) -> bool {
        matches!(self, TreeNode::Leaf(_))
    }
}

/// PathTree is a tree with a string at each non-leaf node.
///
/// If the leaves are JSON values, then this is essentially a JSON object.
#[derive(Debug, Default)]
pub struct PathTree<T> {
    tree: TreeData<T>,
}

impl<T> PathTree<T> {
    pub fn new() -> Self {
        PathTree {
            tree: TreeData::new(),
        }
    }

    /// Set changes the value of the leaf node at the given path.
    ///
    /// Map values do not affect the tree structure---see [`set_subtree`]
    /// instead.
    ///
    /// If the path doesn't refer to a node in the tree, nodes are inserted
    /// and a new leaf is created.
    ///
    /// If path refers to a non-leaf node, that node is replaced by a leaf
    /// and the subtree is discarded.
    // PARITY: Go's Set takes the TreePath by value; taking ownership here too
    // lets the end label move into the map instead of being re-allocated
    // (hot: runsummary FromProto over millions of items).
    pub fn set(&mut self, mut path: TreePath, value: T) {
        let end = path.labels.pop().expect("TreePath labels are non-empty");
        let subtree = get_or_make_subtree(&mut self.tree, &path.labels);
        // Perf: overwrite in place when the key exists (the common case on
        // the summary-ingest hot path) instead of allocating a fresh key
        // String for every insert.
        match subtree.get_mut(&end) {
            Some(node) => *node = TreeNode::Leaf(value),
            None => {
                subtree.insert(end, TreeNode::Leaf(value));
            }
        }
    }

    /// Reserves root-level capacity (perf-only helper, no Go counterpart):
    /// runsummary's FromProto builds a fresh tree whose root holds one entry
    /// per proto item, so growing it incrementally rehashes several times.
    pub(crate) fn reserve_root(&mut self, additional: usize) {
        self.tree.reserve(additional);
    }

    /// Remove deletes a node from the tree.
    pub fn remove(&mut self, path: &TreePath) {
        let Some(subtree) = get_subtree_mut(&mut self.tree, path.prefix()) else {
            return;
        };
        subtree.remove(path.end());
        let mut len = subtree.len();
        let mut path = path.clone();

        // Remove from parents to avoid keeping around empty maps.
        while len == 0 {
            let Some(parent) = path.parent() else {
                return;
            };
            path = parent;

            match get_subtree_mut(&mut self.tree, path.prefix()) {
                Some(subtree) => {
                    subtree.remove(path.end());
                    len = subtree.len();
                }
                // PARITY: Go deletes on a nil map (a no-op) and keeps
                // walking up because len(nil) == 0.
                None => len = 0,
            }
        }
    }

    /// IsEmpty returns whether the tree is empty.
    pub fn is_empty(&self) -> bool {
        self.tree.is_empty()
    }

    /// GetLeaf returns the leaf value at path.
    ///
    /// Returns `None` if the path doesn't lead to a leaf node.
    pub fn get_leaf(&self, path: &TreePath) -> Option<&T> {
        let subtree = get_subtree(&self.tree, path.prefix())?;
        match subtree.get(path.end()) {
            Some(TreeNode::Leaf(value)) => Some(value),
            _ => None,
        }
    }

    /// Mutable variant of [`Self::get_leaf`].
    // PARITY: Go's single GetLeaf returns the value; with T = *metricSummary
    // callers mutate through the pointer (runsummary.Remove). Rust splits
    // the shared/mutable views.
    pub fn get_leaf_mut(&mut self, path: &TreePath) -> Option<&mut T> {
        let subtree = get_subtree_mut(&mut self.tree, path.prefix())?;
        match subtree.get_mut(path.end()) {
            Some(TreeNode::Leaf(value)) => Some(value),
            _ => None,
        }
    }

    /// GetOrMakeLeaf returns the leaf value at path, creating one if
    /// necessary.
    pub fn get_or_make_leaf(
        &mut self,
        path: &TreePath,
        make_default: impl FnOnce() -> T,
    ) -> &mut T {
        let subtree = get_or_make_subtree(&mut self.tree, path.prefix());

        // Perf: replace a non-leaf in place / insert only when missing, so
        // the existing-leaf fast path allocates nothing (hot: runsummary's
        // get_or_make_summary per applied item).
        match subtree.get_mut(path.end()) {
            Some(node) => {
                if !node.is_leaf() {
                    *node = TreeNode::Leaf(make_default());
                }
            }
            None => {
                subtree.insert(path.end().to_string(), TreeNode::Leaf(make_default()));
            }
        }

        match subtree.get_mut(path.end()) {
            Some(TreeNode::Leaf(value)) => value,
            _ => unreachable!("a leaf was just inserted"),
        }
    }

    /// ForEachLeaf runs a callback on each leaf value in the tree.
    ///
    /// The callback returns true to continue and false to stop iteration
    /// early.
    // PARITY: "The order is unspecified and non-deterministic" in Go, and the
    // same holds here (HashMap iteration order). No observable output depends
    // on the order: Updates::apply's per-leaf effects target disjoint paths,
    // and to_summary_tree/to_nested_maps produce keyed maps (serde_json::Map
    // is sorted). Sorting per level was measured at ~30% of the summary
    // ingest of a 287MB run, so the Go behavior is kept instead.
    pub fn for_each_leaf(&self, mut f: impl FnMut(&TreePath, &T) -> bool) {
        // Perf: one TreePath is reused as a push/pop stack across the walk
        // (callbacks only borrow it), instead of allocating a fresh
        // prefix-cloning path per node — this is on the summary-ingest hot
        // path (runsummary Updates::apply over millions of items).
        let mut path = TreePath { labels: Vec::new() };
        for_each_leaf(&self.tree, &mut path, &mut f);
    }
}

impl PathTree<Value> {
    /// CloneTree returns a nested-map representation of the tree.
    ///
    /// This always allocates a new map.
    // PARITY: Go's CloneTree is generic and copies leaves as `any` (slices
    // by reference); here leaves are deep-cloned Values. Only PathTree[any]
    // trees are cloned in the ported subset.
    pub fn clone_tree(&self) -> Map<String, Value> {
        to_nested_maps(&self.tree)
    }
}

fn for_each_leaf<T>(
    tree: &TreeData<T>,
    path: &mut TreePath,
    f: &mut impl FnMut(&TreePath, &T) -> bool,
) -> bool {
    for (key, node) in tree {
        path.labels.push(key.clone());

        let keep_going = match node {
            TreeNode::Leaf(value) => f(path, value),
            TreeNode::Subtree(subtree) => for_each_leaf(subtree, path, f),
        };

        path.labels.pop();
        if !keep_going {
            return false;
        }
    }

    true
}

/// SetSubtree recursively replaces the subtree at the given path.
///
/// The subtree is represented by a map from strings to subtrees or
/// leaf values. This tree structure is copied to update the path
/// tree.
// PARITY: Go: "TODO: this is inefficient---it has repeated getOrMakeSubtree
// calls" — kept as-is.
pub fn set_subtree(pt: &mut PathTree<Value>, path: &TreePath, subtree: &Map<String, Value>) {
    for (key, value) in subtree {
        match value {
            Value::Object(x) => set_subtree(pt, &path.with(key), x),
            _ => pt.set(path.with(key), value.clone()),
        }
    }
}

/// Returns the subtree at the path or `None` if the path doesn't lead to a
/// non-leaf node.
fn get_subtree<'a, T>(tree: &'a TreeData<T>, path: &[String]) -> Option<&'a TreeData<T>> {
    let mut tree = tree;
    for key in path {
        match tree.get(key) {
            Some(TreeNode::Subtree(subtree)) => tree = subtree,
            _ => return None,
        }
    }
    Some(tree)
}

fn get_subtree_mut<'a, T>(
    tree: &'a mut TreeData<T>,
    path: &[String],
) -> Option<&'a mut TreeData<T>> {
    let mut tree = tree;
    for key in path {
        match tree.get_mut(key) {
            Some(TreeNode::Subtree(subtree)) => tree = subtree,
            _ => return None,
        }
    }
    Some(tree)
}

/// Returns the subtree at the path, creating it if necessary.
///
/// Any leaf nodes along the path get overwritten.
fn get_or_make_subtree<'a, T>(tree: &'a mut TreeData<T>, path: &[String]) -> &'a mut TreeData<T> {
    let mut tree = tree;
    for key in path {
        // Perf: probe before entry() — BTreeMap::entry demands an owned key,
        // which would clone `key` even when it is already present (the common
        // case on the summary-ingest hot path).
        if !tree.contains_key(key) {
            tree.insert(key.clone(), TreeNode::Subtree(TreeData::new()));
        }
        let node = tree.get_mut(key).expect("just checked/inserted");
        if node.is_leaf() {
            *node = TreeNode::Subtree(TreeData::new());
        }
        tree = match node {
            TreeNode::Subtree(subtree) => subtree,
            TreeNode::Leaf(_) => unreachable!("leaf was just replaced by a subtree"),
        };
    }
    tree
}

/// Returns a deep copy of the given tree.
fn to_nested_maps(tree: &TreeData<Value>) -> Map<String, Value> {
    let mut clone = Map::new();
    for (key, node) in tree {
        match node {
            TreeNode::Leaf(value) => clone.insert(key.clone(), value.clone()),
            TreeNode::Subtree(subtree) => {
                clone.insert(key.clone(), Value::Object(to_nested_maps(subtree)))
            }
        };
    }
    clone
}

// --- simplejsonext (used subset) ---------------------------------------------

/// Maximum recursion depth for nested values.
const MAX_DEPTH: i32 = 500;

/// Errors from the simplejsonext parser.
// PARITY: message texts mirror the Go module; they surface in
// runsummary.Updates.Apply error strings.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum JsonError {
    /// io.EOF in Go: the data ended where a value or token was required.
    #[error("EOF")]
    Eof,
    #[error("simple json: expected token but found '{0}'")]
    ExpectedToken(char),
    #[error("simple json: expected boolean but found '{0}'")]
    ExpectedBoolean(char),
    #[error("simple json: expected '{want}' but found '{found}'")]
    ExpectedByte { want: char, found: char },
    #[error("simple json: expected {want:?} but found {found:?}")]
    ExpectedLiteral { want: &'static str, found: String },
    #[error("simple json: unexpected comma")]
    UnexpectedComma,
    #[error("simple json: unexpected end of array or object")]
    UnexpectedEnd,
    #[error("simple json: remainder of buffer not empty")]
    BufferNotEmpty,
    #[error("simple json: control character, tab, or newline in string value")]
    ControlChar,
    #[error("simple json: invalid escape {0}")]
    InvalidEscape(char),
    #[error("simple json: expected a unicode hexadecimal codepoint but json is truncated")]
    TruncatedHex,
    #[error("simple json: expected a hexadecimal unicode code point but found {0:?}")]
    InvalidHex(String),
    #[error("simple json: maximum nesting depth exceeded")]
    MaxDepth,
    /// strconv.ParseInt / strconv.ParseFloat failures.
    #[error("parsing {0:?}: invalid syntax")]
    InvalidNumber(String),
}

/// UnmarshalString decodes a JSON representation from `s` as a generic
/// value: int64, float64, string, bool, null, array, or object.
///
/// Accepts `NaN`, `Infinity` and `-Infinity` number literals; integral
/// numbers outside the int64 range decode as floats.
pub fn unmarshal_string(s: &str) -> Result<Value, JsonError> {
    let mut p = Parser {
        data: s.as_bytes(),
        pos: 0,
    };
    let val = p.parse(MAX_DEPTH)?;
    p.check_empty()?;
    Ok(val)
}

/// Encodes an f64 as a Value.
// PARITY: non-finite floats become their Go fmt.Sprint renderings — see the
// module comment.
pub(crate) fn json_float(v: f64) -> Value {
    match serde_json::Number::from_f64(v) {
        Some(n) => Value::Number(n),
        None => Value::String(nonfinite_str(v).to_string()),
    }
}

/// Go's fmt.Sprint rendering of a non-finite float64.
pub(crate) fn nonfinite_str(v: f64) -> &'static str {
    if v.is_nan() {
        "NaN"
    } else if v > 0.0 {
        "+Inf"
    } else {
        "-Inf"
    }
}

const NOT_NUMBER: u8 = 0;
const INTEGRAL_NUMBER: u8 = 1;
const FLOAT_NUMBER: u8 = 2;

/// Character classes inside a number token (Go's numberCharTable).
fn number_char_class(b: u8) -> u8 {
    match b {
        b'0'..=b'9' | b'-' => INTEGRAL_NUMBER,
        // '.', '+', exponents, and the letters of Infinity/NaN.
        b'.' | b'+' | b'e' | b'E' | b'I' | b'n' | b'f' | b'i' | b't' | b'y' | b'N' | b'a' => {
            FLOAT_NUMBER
        }
        _ => NOT_NUMBER,
    }
}

/// b"9223372036854775807", int64_max as text.
const INT64_MAX_TEXT: &[u8] = b"9223372036854775807";
/// b"-9223372036854775808", int64_min as text.
const INT64_MIN_TEXT: &[u8] = b"-9223372036854775808";

fn check_promote_to_float(b: &[u8]) -> bool {
    if b.is_empty() {
        return false;
    }

    let compare: &[u8] = if b[0] == b'-' {
        INT64_MIN_TEXT
    } else {
        INT64_MAX_TEXT
    };

    if b.len() < compare.len() {
        return false;
    }
    if b.len() > compare.len() {
        return true;
    }
    b > compare
}

/// Single-character escapes (Go's escapeTable); `None` is invalid.
fn escape_char(b: u8) -> Option<u8> {
    match b {
        b'b' => Some(0x08),
        b't' => Some(b'\t'),
        b'r' => Some(b'\r'),
        b'n' => Some(b'\n'),
        b'f' => Some(0x0c),
        b'\\' => Some(b'\\'),
        b'/' => Some(b'/'),
        b'"' => Some(b'"'),
        _ => None,
    }
}

fn hex_nibble(b: u8) -> Option<u32> {
    match b {
        b'0'..=b'9' => Some(u32::from(b - b'0')),
        b'a'..=b'f' => Some(u32::from(b - b'a') + 0xa),
        b'A'..=b'F' => Some(u32::from(b - b'A') + 0xa),
        _ => None,
    }
}

/// Value type classes for the next token (Go's typeTable).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ValType {
    Nil,
    Bool,
    Number,
    Str,
    Array,
    Object,
    Comma,
    EndGroup,
}

struct Parser<'a> {
    data: &'a [u8],
    pos: usize,
}

impl Parser<'_> {
    fn skip_spaces(&mut self) {
        while let Some(&b) = self.data.get(self.pos) {
            match b {
                b' ' | b'\n' | b'\t' | b'\r' => self.pos += 1,
                _ => break,
            }
        }
    }

    fn peek(&self) -> Result<u8, JsonError> {
        self.data.get(self.pos).copied().ok_or(JsonError::Eof)
    }

    fn next_byte(&mut self) -> Result<u8, JsonError> {
        let b = self.peek()?;
        self.pos += 1;
        Ok(b)
    }

    /// parseType peeks at the type of the next value without consuming it.
    fn parse_type(&mut self) -> Result<ValType, JsonError> {
        self.skip_spaces();
        let b = self.peek()?;
        match b {
            b'-' | b'0'..=b'9' => Ok(ValType::Number),
            b'I' | b'N' => Ok(ValType::Number), // Infinity, NaN
            b'"' => Ok(ValType::Str),
            b'{' => Ok(ValType::Object),
            b'[' => Ok(ValType::Array),
            b'n' => Ok(ValType::Nil), // null
            b't' | b'f' => Ok(ValType::Bool),
            b',' => Ok(ValType::Comma),
            b']' | b'}' => Ok(ValType::EndGroup),
            _ => Err(JsonError::ExpectedToken(char::from(b))),
        }
    }

    fn read_byte(&mut self, want: u8) -> Result<(), JsonError> {
        let actual = self.next_byte()?;
        if actual != want {
            return Err(JsonError::ExpectedByte {
                want: char::from(want),
                found: char::from(actual),
            });
        }
        Ok(())
    }

    fn read_token(&mut self, token: &'static str) -> Result<(), JsonError> {
        let end = self.pos + token.len();
        if end > self.data.len() {
            return Err(JsonError::Eof);
        }
        let actual = &self.data[self.pos..end];
        if actual != token.as_bytes() {
            return Err(JsonError::ExpectedLiteral {
                want: token,
                found: String::from_utf8_lossy(actual).into_owned(),
            });
        }
        self.pos = end;
        Ok(())
    }

    fn parse(&mut self, remaining_depth: i32) -> Result<Value, JsonError> {
        if remaining_depth < 0 {
            return Err(JsonError::MaxDepth);
        }
        match self.parse_type()? {
            ValType::Nil => {
                self.read_token("null")?;
                Ok(Value::Null)
            }
            ValType::Bool => self.parse_bool(),
            ValType::Number => self.parse_number(),
            ValType::Str => Ok(Value::String(self.parse_string()?)),
            ValType::Array => self.parse_array(remaining_depth),
            ValType::Object => self.parse_object(remaining_depth),
            ValType::Comma => Err(JsonError::UnexpectedComma),
            ValType::EndGroup => Err(JsonError::UnexpectedEnd),
        }
    }

    fn parse_bool(&mut self) -> Result<Value, JsonError> {
        match self.peek()? {
            b'f' => {
                self.read_token("false")?;
                Ok(Value::Bool(false))
            }
            b't' => {
                self.read_token("true")?;
                Ok(Value::Bool(true))
            }
            b => Err(JsonError::ExpectedBoolean(char::from(b))),
        }
    }

    fn parse_number(&mut self) -> Result<Value, JsonError> {
        let start = self.pos;
        let mut ty = INTEGRAL_NUMBER;
        while let Some(&b) = self.data.get(self.pos) {
            match number_char_class(b) {
                NOT_NUMBER => break,
                FLOAT_NUMBER => {
                    ty = FLOAT_NUMBER;
                    self.pos += 1;
                }
                _ => self.pos += 1,
            }
        }
        let view = &self.data[start..self.pos];
        // Number tokens are all ASCII by construction.
        let text = str::from_utf8(view).expect("number tokens are ASCII");

        if ty == FLOAT_NUMBER || check_promote_to_float(view) {
            // PARITY: Go uses strconv.ParseFloat and swallows ErrRange, so
            // overflowing values become ±Inf and underflowing ones 0; Rust's
            // f64 parser saturates identically. Both accept the symbols
            // "Inf", "Infinity", and "NaN" (case-insensitively, signed).
            let v: f64 = text
                .parse()
                .map_err(|_| JsonError::InvalidNumber(text.to_string()))?;
            Ok(json_float(v))
        } else {
            let v: i64 = text
                .parse()
                .map_err(|_| JsonError::InvalidNumber(text.to_string()))?;
            Ok(Value::from(v))
        }
    }

    fn parse_string(&mut self) -> Result<String, JsonError> {
        // Consume the initial quote.
        if self.peek()? != b'"' {
            return Err(JsonError::ExpectedByte {
                want: '"',
                found: char::from(self.peek()?),
            });
        }
        self.pos += 1;

        let mut out: Vec<u8> = Vec::new();
        // Tracks whether we are combining a surrogate pair. If we are not,
        // this value will be zero (None).
        let mut open_surrogate: Option<u32> = None;

        loop {
            let b = self.next_byte()?;
            if b < b' ' {
                return Err(JsonError::ControlChar);
            }
            if b == b'\\' {
                let e = self.next_byte()?;
                if e < b' ' {
                    return Err(JsonError::ControlChar);
                }
                if e == b'u' {
                    // Unicode escape! This is a \u which must be followed by
                    // 4 hex characters.
                    if self.pos + 4 > self.data.len() {
                        return Err(JsonError::TruncatedHex);
                    }
                    let hex = &self.data[self.pos..self.pos + 4];
                    self.pos += 4;
                    let this_rune = parse_hex_to_rune(hex)?;
                    // Handle any existing open surrogate.
                    if let Some(open) = open_surrogate {
                        if (0xdc00..=0xdfff).contains(&this_rune) {
                            // Success! This rune is a low surrogate, and both
                            // the open surrogate and this current rune are
                            // consumed.
                            let combined = 0x10000 + ((open - 0xd800) << 10) + (this_rune - 0xdc00);
                            push_rune(&mut out, combined);
                            open_surrogate = None;
                            continue;
                        }
                        // Previous rune was unpaired; write it now.
                        push_rune(&mut out, 0xfffd);
                        open_surrogate = None;
                    }
                    if (0xd800..=0xdfff).contains(&this_rune) {
                        if this_rune >= 0xdc00 {
                            // This rune is an unpaired low surrogate.
                            push_rune(&mut out, 0xfffd);
                        } else {
                            // Success! This rune is a high surrogate. Store it!
                            open_surrogate = Some(this_rune);
                        }
                    } else {
                        // This is a normal unicode-escaped rune.
                        push_rune(&mut out, this_rune);
                    }
                    continue;
                }
                // Non-unicode, single-character escape. Use the LUT.
                if open_surrogate.take().is_some() {
                    push_rune(&mut out, 0xfffd);
                }
                let Some(mapped) = escape_char(e) else {
                    return Err(JsonError::InvalidEscape(char::from(e)));
                };
                out.push(mapped);
                continue;
            }
            if b == b'"' {
                // We found the end of the string!
                if open_surrogate.is_some() {
                    push_rune(&mut out, 0xfffd);
                }
                // PARITY: Go strings may hold arbitrary bytes; here the
                // input is a &str so raw bytes are already valid UTF-8 and
                // the lossy conversion never rewrites anything.
                return Ok(String::from_utf8_lossy(&out).into_owned());
            }
            // A (normal) non-escaped byte.
            if open_surrogate.take().is_some() {
                push_rune(&mut out, 0xfffd);
            }
            out.push(b);
        }
    }

    fn parse_array(&mut self, remaining_depth: i32) -> Result<Value, JsonError> {
        // Consume the opening bracket.
        self.read_byte(b'[')?;
        let mut arr: Vec<Value> = Vec::new();
        loop {
            let ty = self.parse_type()?;
            if ty == ValType::EndGroup {
                // Found an ending brace/bracket immediately after the start
                // of the array or one of its values, cleanly ending the array.
                self.read_byte(b']')?;
                break;
            } else if arr.is_empty() {
                if ty == ValType::Comma {
                    // Found a comma with no previous value.
                    return Err(JsonError::UnexpectedComma);
                }
            } else {
                // We just read a value and the array hasn't ended. We MUST
                // find a comma next, and we have already skipped whitespace.
                self.read_byte(b',')?;
            }
            // We now have a regular following value, not an errant comma or
            // the end of the array. (A trailing comma is an error: the
            // recursive parse sees the ']' and reports UnexpectedEnd, as in
            // Go.)
            arr.push(self.parse(remaining_depth - 1)?);
        }
        Ok(Value::Array(arr))
    }

    fn parse_object(&mut self, remaining_depth: i32) -> Result<Value, JsonError> {
        // Consume the beginning of the object.
        self.read_byte(b'{')?;
        // PARITY: Go returns a nil map for "{}" (the map is only allocated
        // once an item is seen); a nil and an empty map behave identically
        // everywhere this value flows (type switches, SetSubtree, ranges).
        let mut obj = Map::new();
        let mut saw_item = false;
        loop {
            let ty = self.parse_type()?;
            if ty == ValType::EndGroup {
                self.read_byte(b'}')?;
                break;
            } else if !saw_item {
                if ty == ValType::Comma {
                    // Found a comma with no previous value.
                    return Err(JsonError::UnexpectedComma);
                }
                saw_item = true;
            } else {
                // We just parsed an item and the object hasn't ended. We
                // MUST find a comma next.
                self.read_byte(b',')?;
            }
            // We now have a regular following item, not an errant comma or
            // the end of the object. (A trailing comma is an error: the key
            // parse sees the '}' and fails, as in Go.)
            self.skip_spaces();
            // Read the map key, which MUST be a string.
            let key = self.parse_string()?;
            // Consume the ':' separating the key and value.
            self.skip_spaces();
            self.read_byte(b':')?;
            // Duplicate keys: the last value wins, as with Go map assignment.
            obj.insert(key, self.parse(remaining_depth - 1)?);
        }
        Ok(Value::Object(obj))
    }

    /// CheckEmpty checks that the remaining data is all whitespace.
    fn check_empty(&mut self) -> Result<(), JsonError> {
        self.skip_spaces();
        if self.pos < self.data.len() {
            return Err(JsonError::BufferNotEmpty);
        }
        Ok(())
    }
}

/// Given 4 bytes of hexadecimal text, returns the corresponding code point.
fn parse_hex_to_rune(chunk: &[u8]) -> Result<u32, JsonError> {
    let (Some(a), Some(b), Some(c), Some(d)) = (
        hex_nibble(chunk[0]),
        hex_nibble(chunk[1]),
        hex_nibble(chunk[2]),
        hex_nibble(chunk[3]),
    ) else {
        return Err(JsonError::InvalidHex(
            String::from_utf8_lossy(chunk).into_owned(),
        ));
    };
    Ok((a << 12) | (b << 8) | (c << 4) | d)
}

/// Appends a code point to the byte buffer as UTF-8.
fn push_rune(out: &mut Vec<u8>, rune: u32) {
    // PARITY: Go's WriteRune writes U+FFFD for invalid runes; surrogate
    // handling above never passes one, but mirror the fallback.
    let c = char::from_u32(rune).unwrap_or('\u{fffd}');
    let mut buf = [0u8; 4];
    out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
}

// --- runconfig (used subset) --------------------------------------------------

/// The configuration of a run.
///
/// This is usually used for hyperparameters and some run metadata like the
/// start time and the ML framework used. In a somewhat hacky way, it is also
/// used to store programmatic custom charts for the run and various other
/// things.
///
/// The server process builds this up incrementally throughout a run's
/// lifetime.
// PARITY: used subset — Serialize / AddInternalData / MergeResumedConfig are
// not needed by runoverview.go and are not ported.
#[derive(Debug, Default)]
pub struct RunConfig {
    path_tree: PathTree<Value>,
}

impl RunConfig {
    pub fn new() -> Self {
        RunConfig {
            path_tree: PathTree::new(),
        }
    }

    pub fn new_from(tree: Map<String, Value>) -> Self {
        let mut rc = RunConfig::new();

        for (key, value) in &tree {
            match value {
                Value::Object(x) => set_subtree(&mut rc.path_tree, &TreePath::path_of(key, &[]), x),
                _ => rc.path_tree.set(TreePath::path_of(key, &[]), value.clone()),
            }
        }

        rc
    }

    /// Updates and/or removes values from the configuration tree.
    ///
    /// Does a best-effort job to apply all changes. Errors are passed to
    /// `on_error` and skipped.
    pub fn apply_change_record(
        &mut self,
        config_record: &ConfigRecord,
        mut on_error: impl FnMut(JsonError),
    ) {
        for item in &config_record.update {
            let value = match unmarshal_string(&item.value_json) {
                Ok(value) => value,
                Err(err) => {
                    on_error(err);
                    continue;
                }
            };

            match value {
                Value::Object(x) => set_subtree(&mut self.path_tree, &key_path(item), &x),
                _ => self.path_tree.set(key_path(item), value),
            }
        }

        for item in &config_record.remove {
            self.path_tree.remove(&key_path(item));
        }
    }

    pub fn clone_tree(&self) -> Map<String, Value> {
        self.path_tree.clone_tree()
    }
}

/// keyPath returns the key path for the given config item.
/// If the item has a nested key, it returns the nested key.
/// Otherwise, it returns a slice with the key.
fn key_path(item: &ConfigItem) -> TreePath {
    if !item.nested_key.is_empty() {
        return TreePath::from_labels(item.nested_key.clone());
    }
    TreePath::from_labels(vec![item.key.clone()])
}

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;
    use serde_json::json;

    use super::*;

    fn json_map(v: Value) -> Map<String, Value> {
        match v {
            Value::Object(m) => m,
            _ => panic!("expected a JSON object"),
        }
    }

    // Transliterated from core/internal/runconfig/runconfig_test.go.
    // TestConfigSerialize and TestAddInternalData cover Serialize /
    // AddInternalData, which are outside the ported subset.

    #[test]
    fn config_update() {
        let mut run_config = RunConfig::new_from(json_map(json!({
            "b": {
                "c": 321.0,
                "d": 123.0,
            },
        })));

        run_config.apply_change_record(
            &ConfigRecord {
                update: vec![
                    ConfigItem {
                        key: "a".to_string(),
                        value_json: "1".to_string(),
                        ..Default::default()
                    },
                    ConfigItem {
                        nested_key: vec!["b".to_string(), "c".to_string()],
                        value_json: "\"text\"".to_string(),
                        ..Default::default()
                    },
                ],
                ..Default::default()
            },
            ignore_error,
        );

        assert_eq!(
            run_config.clone_tree(),
            json_map(json!({
                "a": 1,
                "b": {
                    "c": "text",
                    "d": 123.0,
                },
            })),
        );
    }

    #[test]
    fn config_remove() {
        let mut run_config = RunConfig::new_from(json_map(json!({
            "a": 9,
            "b": {
                "c": 321.0,
                "d": 123.0,
            },
        })));

        run_config.apply_change_record(
            &ConfigRecord {
                remove: vec![
                    ConfigItem {
                        key: "a".to_string(),
                        ..Default::default()
                    },
                    ConfigItem {
                        nested_key: vec!["b".to_string(), "c".to_string()],
                        ..Default::default()
                    },
                ],
                ..Default::default()
            },
            ignore_error,
        );

        assert_eq!(
            run_config.clone_tree(),
            json_map(json!({"b": {"d": 123.0}}))
        );
    }

    fn ignore_error(_err: JsonError) {}

    #[test]
    fn clone_tree() {
        // PARITY: the Go test stores []string and int leaves in the tree;
        // values here are the equivalent JSON values.
        let run_config = RunConfig::new_from(json_map(json!({
            "number": 9,
            "nested": {
                "list": ["a", "b", "c"],
                "text": "xyz",
            },
        })));
        let mut cloned = run_config.clone_tree();
        assert_eq!(
            cloned,
            json_map(json!({
                "number": 9,
                "nested": {
                    "list": ["a", "b", "c"],
                    "text": "xyz",
                },
            })),
        );
        // Delete elements from the cloned tree and check that the original
        // is unchanged.
        cloned.remove("number");
        cloned
            .get_mut("nested")
            .and_then(Value::as_object_mut)
            .expect("nested is an object")
            .remove("list");
        assert_eq!(
            run_config.clone_tree(),
            json_map(json!({
                "number": 9,
                "nested": {
                    "list": ["a", "b", "c"],
                    "text": "xyz",
                },
            })),
        );
    }

    // Transliterated from core/internal/pathtree/pathtree_test.go (the used
    // subset; TestFlatten covers Flatten, which is not ported).

    #[test]
    fn set_new_node() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &["b"]), 1);
        tree.set(TreePath::path_of("a", &["c", "d"]), 2);

        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &["b"])), Some(&1));
        assert_eq!(
            tree.get_leaf(&TreePath::path_of("a", &["c", "d"])),
            Some(&2)
        );
    }

    #[test]
    fn set_overwrite_leaf() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &[]), 1);
        tree.set(TreePath::path_of("a", &["b"]), 2);

        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &[])), None);
        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &["b"])), Some(&2));
    }

    #[test]
    fn remove_leaf() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &["b"]), 1);
        tree.set(TreePath::path_of("a", &["c"]), 2);
        tree.remove(&TreePath::path_of("a", &["b"]));

        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &["b"])), None);
        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &["c"])), Some(&2));
    }

    #[test]
    fn remove_node() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &["b", "c"]), 1);
        tree.set(TreePath::path_of("a", &["d"]), 2);
        tree.remove(&TreePath::path_of("a", &["b"]));

        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &["b", "c"])), None);
        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &["d"])), Some(&2));
    }

    #[test]
    fn remove_deletes_parent_maps() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &["b", "c"]), 1);
        tree.remove(&TreePath::path_of("a", &["b", "c"]));

        // IsEmpty() just checks the length of the root map. If we don't
        // remove parent maps, this will fail.
        assert!(tree.is_empty());
    }

    #[test]
    fn get_leaf_under_leaf() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &[]), 1);

        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &["b"])), None);
    }

    #[test]
    fn get_leaf_path_is_not_leaf() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &["b"]), 1);

        assert_eq!(tree.get_leaf(&TreePath::path_of("a", &[])), None);
    }

    #[test]
    fn get_or_make_leaf_path_is_not_leaf() {
        let mut tree: PathTree<i64> = PathTree::new();

        tree.set(TreePath::path_of("a", &["b"]), 1);

        let x = tree.get_or_make_leaf(&TreePath::path_of("a", &[]), || 2);
        assert_eq!(*x, 2);
    }

    // Anchor tests for the simplejsonext used-subset port (the Go module's
    // behavior, pinned where runconfig/runsummary depend on it).

    #[test]
    fn unmarshal_int_vs_float() {
        assert_eq!(unmarshal_string("1").unwrap(), json!(1));
        assert_eq!(unmarshal_string("-5").unwrap(), json!(-5));
        assert_eq!(unmarshal_string("0.01").unwrap(), json!(0.01));
        assert_eq!(unmarshal_string("1e3").unwrap(), json!(1000.0));
        assert_eq!(unmarshal_string("1.0").unwrap(), json!(1.0));
        // int64 bounds stay integral...
        assert_eq!(
            unmarshal_string("9223372036854775807").unwrap(),
            json!(i64::MAX)
        );
        assert_eq!(
            unmarshal_string("-9223372036854775808").unwrap(),
            json!(i64::MIN)
        );
        // ...and beyond them the text is re-parsed as a float.
        assert_eq!(
            unmarshal_string("9223372036854775808").unwrap(),
            json!(9.223372036854776e18),
        );
    }

    #[test]
    fn unmarshal_nonfinite_literals() {
        // PARITY: floats that serde_json can't hold are stored as their Go
        // fmt.Sprint renderings.
        assert_eq!(unmarshal_string("NaN").unwrap(), json!("NaN"));
        assert_eq!(unmarshal_string("Infinity").unwrap(), json!("+Inf"));
        assert_eq!(unmarshal_string("-Infinity").unwrap(), json!("-Inf"));
        // Overflow saturates to infinity, as in Go (ErrRange is swallowed).
        assert_eq!(unmarshal_string("1e999").unwrap(), json!("+Inf"));
    }

    #[test]
    fn unmarshal_structures_and_strings() {
        assert_eq!(
            unmarshal_string(r#"{"a": [1, {"b": null}, "xé\n"], "t": true}"#).unwrap(),
            json!({"a": [1, {"b": null}, "xé\n"], "t": true}),
        );
        assert_eq!(unmarshal_string(r#""😀""#).unwrap(), json!("😀"));
        // Unpaired surrogates decode to U+FFFD.
        assert_eq!(
            unmarshal_string(r#""\ud83dx""#).unwrap(),
            json!("\u{fffd}x")
        );
        assert_eq!(unmarshal_string("{}").unwrap(), json!({}));
        assert_eq!(unmarshal_string("[]").unwrap(), json!([]));
    }

    #[test]
    fn unmarshal_errors() {
        assert_eq!(
            unmarshal_string("<not valid JSON>"),
            Err(JsonError::ExpectedToken('<'))
        );
        assert_eq!(unmarshal_string(""), Err(JsonError::Eof));
        assert_eq!(unmarshal_string("1 2"), Err(JsonError::BufferNotEmpty));
        assert_eq!(unmarshal_string("[,1]"), Err(JsonError::UnexpectedComma));
        // Trailing commas are errors, as in Go.
        assert_eq!(unmarshal_string("[1,]"), Err(JsonError::UnexpectedEnd));
        assert_eq!(
            unmarshal_string(r#"{"a":1,}"#),
            Err(JsonError::ExpectedByte {
                want: '"',
                found: '}'
            }),
        );
        // PARITY: lowercase "nan" dispatches as a null literal ('n' in the
        // type table); with fewer bytes left than the token Go's read()
        // returns io.EOF, with enough bytes it reports the mismatch.
        assert_eq!(unmarshal_string("nan"), Err(JsonError::Eof));
        assert_eq!(
            unmarshal_string("nan "),
            Err(JsonError::ExpectedLiteral {
                want: "null",
                found: "nan ".to_string()
            }),
        );
    }
}
