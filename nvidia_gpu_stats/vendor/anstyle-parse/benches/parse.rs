#![allow(clippy::incompatible_msrv)] // not verifying benches atm

use std::hint::black_box;

use anstyle_parse::DefaultCharAccumulator;
use anstyle_parse::Params;
use anstyle_parse::Parser;
use anstyle_parse::Perform;

#[divan::bench(args = DATA)]
fn advance(data: &Data) {
    let mut dispatcher = BenchDispatcher;
    let mut parser = Parser::<DefaultCharAccumulator>::new();

    for byte in data.content() {
        parser.advance(&mut dispatcher, *byte);
    }
}

#[divan::bench(args = DATA)]
fn advance_strip(data: &Data) -> String {
    let mut stripped = Strip::with_capacity(data.content().len());
    let mut parser = Parser::<DefaultCharAccumulator>::new();

    for byte in data.content() {
        parser.advance(&mut stripped, *byte);
    }

    black_box(stripped.0)
}

#[divan::bench(args = DATA)]
fn state_change(data: &Data) {
    let mut state = anstyle_parse::state::State::default();
    for byte in data.content() {
        let (next_state, action) = anstyle_parse::state::state_change(state, *byte);
        state = next_state;
        black_box(action);
    }
}

#[divan::bench(args = DATA)]
fn state_change_strip_str(bencher: divan::Bencher<'_, '_>, data: &Data) {
    if let Ok(content) = std::str::from_utf8(data.content()) {
        bencher
            .with_inputs(|| content)
            .bench_local_values(|content| {
                let stripped = strip_str(content);

                black_box(stripped)
            });
    }
}

struct BenchDispatcher;
impl Perform for BenchDispatcher {
    fn print(&mut self, c: char) {
        black_box(c);
    }

    fn execute(&mut self, byte: u8) {
        black_box(byte);
    }

    fn hook(&mut self, params: &Params, intermediates: &[u8], ignore: bool, c: u8) {
        black_box((params, intermediates, ignore, c));
    }

    fn put(&mut self, byte: u8) {
        black_box(byte);
    }

    fn osc_dispatch(&mut self, params: &[&[u8]], bell_terminated: bool) {
        black_box((params, bell_terminated));
    }

    fn csi_dispatch(&mut self, params: &Params, intermediates: &[u8], ignore: bool, c: u8) {
        black_box((params, intermediates, ignore, c));
    }

    fn esc_dispatch(&mut self, intermediates: &[u8], ignore: bool, byte: u8) {
        black_box((intermediates, ignore, byte));
    }
}

#[derive(Default)]
struct Strip(String);
impl Strip {
    fn with_capacity(capacity: usize) -> Self {
        Self(String::with_capacity(capacity))
    }
}
impl Perform for Strip {
    fn print(&mut self, c: char) {
        self.0.push(c);
    }

    fn execute(&mut self, byte: u8) {
        if byte.is_ascii_whitespace() {
            self.0.push(byte as char);
        }
    }
}

fn strip_str(content: &str) -> String {
    use anstyle_parse::state::state_change;
    use anstyle_parse::state::Action;
    use anstyle_parse::state::State;

    #[inline]
    fn is_utf8_continuation(b: u8) -> bool {
        matches!(b, 0x80..=0xbf)
    }

    #[inline]
    fn is_printable(action: Action, byte: u8) -> bool {
        action == Action::Print
                    || action == Action::BeginUtf8
                    // since we know the input is valid UTF-8, the only thing  we can do with
                    // continuations is to print them
                    || is_utf8_continuation(byte)
                    || (action == Action::Execute && byte.is_ascii_whitespace())
    }

    let mut stripped = Vec::with_capacity(content.len());

    let mut bytes = content.as_bytes();
    while !bytes.is_empty() {
        let offset = bytes.iter().copied().position(|b| {
            let (_next_state, action) = state_change(State::Ground, b);
            !is_printable(action, b)
        });
        let (printable, next) = bytes.split_at(offset.unwrap_or(bytes.len()));
        stripped.extend(printable);
        bytes = next;

        let mut state = State::Ground;
        let offset = bytes.iter().copied().position(|b| {
            let (next_state, action) = state_change(state, b);
            if next_state != State::Anywhere {
                state = next_state;
            }
            is_printable(action, b)
        });
        let (_, next) = bytes.split_at(offset.unwrap_or(bytes.len()));
        bytes = next;
    }

    #[allow(clippy::unwrap_used)]
    String::from_utf8(stripped).unwrap()
}

const DATA: &[Data] = &[
    Data(
        "0-state_changes",
        b"\x1b]2;X\x1b\\ \x1b[0m \x1bP0@\x1b\\".as_slice(),
    ),
    #[cfg(feature = "utf8")]
    Data("1-demo.vte", include_bytes!("../tests/demo.vte").as_slice()),
    Data(
        "2-rg_help.vte",
        include_bytes!("../tests/rg_help.vte").as_slice(),
    ),
    Data(
        "3-rg_linus.vte",
        include_bytes!("../tests/rg_linus.vte").as_slice(),
    ),
];

#[derive(Debug)]
struct Data(&'static str, &'static [u8]);

impl Data {
    const fn name(&self) -> &'static str {
        self.0
    }

    const fn content(&self) -> &'static [u8] {
        self.1
    }
}

impl std::fmt::Display for Data {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.name().fmt(f)
    }
}

#[test]
fn verify_data() {
    for data in DATA {
        let Data(name, content) = data;
        // Make sure the comparison is fair
        if let Ok(content) = std::str::from_utf8(content) {
            let mut stripped = Strip::with_capacity(content.len());
            let mut parser = Parser::<DefaultCharAccumulator>::new();
            for byte in content.as_bytes() {
                parser.advance(&mut stripped, *byte);
            }
            assert_eq!(stripped.0, strip_str(content));
        }
    }
}

fn main() {
    divan::main();
}
