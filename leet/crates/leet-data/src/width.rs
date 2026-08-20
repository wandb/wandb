//! Display-width shim reproducing what Go leet sees from `lipgloss.Width`.
//!
//! The Go chain (all vendored under `core/vendor/`, versions from
//! `core/vendor/modules.txt`) is:
//!
//! - `charm.land/lipgloss/v2` v2.0.5 `Width` (size.go:15): splits on `\n`,
//!   returns the max `ansi.StringWidth` across lines.
//! - `github.com/charmbracelet/x/ansi` v0.11.7 `StringWidth` (width.go:65,
//!   `GraphemeWidth` method): feeds bytes through the DEC ANSI parser table
//!   (parser/transition_table.go); escape sequences and control bytes count
//!   as 0, printable runs are consumed grapheme cluster by grapheme cluster
//!   (parser_decode.go:435 `FirstGraphemeCluster`).
//! - `github.com/clipperhouse/uax29/v2` v2.7.0 `graphemes`: UAX #29 extended
//!   grapheme cluster segmentation, Unicode 17.0.0 data.
//! - `github.com/clipperhouse/displaywidth` v0.11.0 (width.go:149
//!   `graphemeWidth`) with `Options{EastAsianWidth: false}` (ansi/method.go:16
//!   `dwOptions`): a cluster's width is the width property of its FIRST code
//!   point (Wide=2, Zero_Width=0, East_Asian_Ambiguous=1, Default=1), except
//!   a VS16 (U+FE0F) as the SECOND code point promotes any non-Wide cluster
//!   to Wide. Unicode 17.0.0 East Asian Width + emoji data.
//!
//! The Rust side uses `unicode-segmentation` (Unicode 17) for clusters and
//! `unicode-width` (Unicode 17) plus explicit override tables for the first
//! code point's property, verified against a full-scalar differential dump
//! of the Go chain (see the test module).
//!
//! All column math in the port MUST go through [`text_width`] /
//! [`line_width`] / [`grapheme_width`]; nothing else may call
//! `unicode_width` directly (PORTING.md, architecture pattern map).

use unicode_segmentation::UnicodeSegmentation;
use unicode_width::UnicodeWidthChar;

/// `lipgloss.Width` (lipgloss/v2 size.go:15): the max [`line_width`] over
/// `\n`-split lines. ANSI escape sequences measure 0.
pub fn text_width(s: &str) -> usize {
    s.split('\n').map(line_width).max().unwrap_or(0)
}

/// `ansi.StringWidth` (x/ansi width.go:65) with the `GraphemeWidth` method:
/// the terminal cell width of one line, skipping ANSI escape sequences.
///
/// Mirrors `stringWidth`'s byte loop: run each byte through the DEC parser
/// transition table; on a printable byte (`PrintAction`, i.e. 0x20..=0x7E in
/// ground state) or a UTF-8 lead byte (`Utf8State`), consume one full
/// grapheme cluster, add its width, and reset to ground state. Everything
/// else (C0/C1 controls, escape sequence bytes) contributes 0.
pub fn line_width(s: &str) -> usize {
    let bytes = s.as_bytes();
    let mut state = State::Ground;
    let mut width = 0usize;
    let mut i = 0usize;
    while i < bytes.len() {
        let (next, cluster) = transition(state, bytes[i]);
        if cluster {
            // `cluster` is only produced for printable ASCII or a UTF-8 lead
            // byte, both of which are char boundaries in a valid &str, so
            // slicing here cannot panic.
            let rest = &s[i..];
            let g = rest.graphemes(true).next().unwrap_or(rest);
            width += grapheme_width(g);
            i += g.len();
            state = State::Ground; // stringWidth resets pstate to GroundState
            continue;
        }
        state = next;
        i += 1;
    }
    width
}

/// `displaywidth.graphemeWidth` (displaywidth width.go:149) with
/// `EastAsianWidth: false`: the cell width of a single grapheme cluster.
///
/// The width of a multi-code-point cluster is the width property of its
/// FIRST code point; combining marks, ZWJ continuations, regional-indicator
/// pairs, skin-tone modifiers etc. never add width. A VS16 (U+FE0F) as the
/// second code point promotes a non-Wide cluster to Wide (width 2) — even
/// for non-emoji bases like `"A\u{FE0F}"` (displaywidth width.go:175). VS15
/// (U+FE0E) has no width effect (comment at displaywidth width.go:180).
pub fn grapheme_width(cluster: &str) -> usize {
    let bytes = cluster.as_bytes();
    if bytes.is_empty() {
        return 0;
    }
    // dwOptions.ControlSequences8Bit is false, so the C1 fast path at
    // displaywidth width.go:157 is inert; C1 handling happens via the
    // property lookup below.
    //
    // Single-byte clusters skip the property lookup (width.go:162).
    if bytes.len() == 1 {
        return ascii_width(bytes[0]);
    }
    // Multi-byte grapheme clusters led by a C0 control, e.g. "\r\n"
    // (width.go:167).
    if bytes[0] <= 0x1F {
        return 0;
    }
    let first = match cluster.chars().next() {
        Some(c) => c,
        None => return 0, // unreachable: non-empty &str has a first char
    };
    let sz = first.len_utf8();
    let mut prop = scalar_property(first);
    // Variation Selector 16 requests emoji presentation (width.go:175):
    // promote iff the base is not already Wide and the bytes immediately
    // after the first code point are exactly EF B8 8F (U+FE0F). Byte-wise
    // like Go; no 3-byte prefix of another char can alias this.
    if prop != Prop::Wide && bytes.len() >= sz + 3 && bytes[sz..sz + 3] == [0xEF, 0xB8, 0x8F] {
        prop = Prop::Wide;
    }
    // EastAsianWidth=false: East_Asian_Ambiguous stays width 1 (width.go:185
    // not taken), already folded into Prop::Narrow by scalar_property.
    match prop {
        Prop::Wide => 2,
        Prop::ZeroWidth => 0,
        Prop::Narrow => 1,
    }
}

/// `displaywidth.asciiWidth` (width.go:196): C0 controls and DEL are 0,
/// other single bytes are 1.
fn ascii_width(b: u8) -> usize {
    if b <= 0x1F || b == 0x7F { 0 } else { 1 }
}

/// The width property displaywidth's generated trie assigns to a code point,
/// with East_Asian_Ambiguous folded into `Narrow` (dwOptions has
/// `EastAsianWidth: false`, so both are width 1).
#[derive(Clone, Copy, PartialEq, Eq)]
enum Prop {
    Narrow,
    ZeroWidth,
    Wide,
}

/// First-code-point property lookup: `unicode-width`'s per-char width plus
/// override tables for the (few) places displaywidth's Unicode 17 trie
/// disagrees with unicode-width's tables. The override ranges were derived
/// by diffing a full-scalar sweep of Go `lipgloss.Width` against this
/// function (see the test module for the regeneration command).
fn scalar_property(c: char) -> Prop {
    let cp = c as u32;
    if in_table(&WIDE_OVERRIDES, cp) {
        return Prop::Wide;
    }
    if in_table(&NARROW_OVERRIDES, cp) {
        return Prop::Narrow;
    }
    if in_table(&ZERO_OVERRIDES, cp) {
        return Prop::ZeroWidth;
    }
    match c.width() {
        // unicode-width returns None for C0/C1 controls and DEL; displaywidth
        // classifies C1 (the only ones that can reach a property lookup, as
        // 2-byte UTF-8) as Zero_Width — the Go sweep reports 0 for
        // U+0080..=U+009F.
        None | Some(0) => Prop::ZeroWidth,
        Some(2) => Prop::Wide,
        Some(_) => Prop::Narrow,
    }
}

fn in_table(table: &[(u32, u32)], cp: u32) -> bool {
    table
        .binary_search_by(|&(lo, hi)| {
            if cp < lo {
                core::cmp::Ordering::Greater
            } else if cp > hi {
                core::cmp::Ordering::Less
            } else {
                core::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

// The override tables below were generated by diffing a full-scalar-sweep of
// Go `lipgloss.Width` (the exact vendored chain) against this module with
// empty tables; see the test module's `GO_SINGLE_SCALAR_RUNS` header for the
// regeneration commands. Both data sets are Unicode 17.0.0; the disagreement
// is in bucketing, not Unicode versions:
//
// - Wide: displaywidth marks Regional Indicators and a few East_Asian_Wide
//   combining marks (Hangul tone marks, the Hangul filler, Vietnamese
//   reading marks) `_Wide`; unicode-width gives them 1 resp. 0.
// - Narrow: displaywidth leaves conjoining Hangul jamo V/T, the
//   Other_Grapheme_Extend spacing marks (Bengali/Tamil/... vowel signs and
//   length marks), and reserved-but-unassigned code points in
//   default-ignorable ranges at `_Default` (1); unicode-width zeroes them.
// - Zero: displaywidth marks prepended concatenation marks (Arabic number
//   signs etc.), line/paragraph separators, interlinear annotation
//   controls, noncharacters U+FFFE/U+FFFF, and Egyptian hieroglyph format
//   controls `_Zero_Width`; unicode-width gives them 1.

/// Code points displaywidth marks `_Wide` but unicode-width does not give
/// width 2. Sorted, inclusive ranges.
const WIDE_OVERRIDES: [(u32, u32); 4] = [
    (0x302E, 0x302F),   // HANGUL SINGLE DOT TONE MARK .. HANGUL DOUBLE DOT TONE MARK
    (0x3164, 0x3164),   // HANGUL FILLER
    (0x16FF0, 0x16FF1), // VIETNAMESE ALTERNATE READING MARK CA .. NHAY
    (0x1F1E6, 0x1F1FF), // REGIONAL INDICATOR SYMBOL LETTER A .. Z
];

/// Code points displaywidth marks `_Default`/`_East_Asian_Ambiguous`
/// (width 1) but unicode-width gives 0 or 2. Sorted, inclusive ranges.
const NARROW_OVERRIDES: [(u32, u32); 81] = [
    (0x0897, 0x0897),   // ARABIC PEPET
    (0x09BE, 0x09BE),   // BENGALI VOWEL SIGN AA
    (0x09D7, 0x09D7),   // BENGALI AU LENGTH MARK
    (0x0B3E, 0x0B3E),   // ORIYA VOWEL SIGN AA
    (0x0B57, 0x0B57),   // ORIYA AU LENGTH MARK
    (0x0BBE, 0x0BBE),   // TAMIL VOWEL SIGN AA
    (0x0BD7, 0x0BD7),   // TAMIL AU LENGTH MARK
    (0x0CC0, 0x0CC0),   // KANNADA VOWEL SIGN II
    (0x0CC2, 0x0CC2),   // KANNADA VOWEL SIGN UU
    (0x0CC7, 0x0CC8),   // KANNADA VOWEL SIGN EE .. AI
    (0x0CCA, 0x0CCB),   // KANNADA VOWEL SIGN O .. OO
    (0x0CD5, 0x0CD6),   // KANNADA LENGTH MARK .. AI LENGTH MARK
    (0x0D3E, 0x0D3E),   // MALAYALAM VOWEL SIGN AA
    (0x0D4E, 0x0D4E),   // MALAYALAM LETTER DOT REPH
    (0x0D57, 0x0D57),   // MALAYALAM AU LENGTH MARK
    (0x0DCF, 0x0DCF),   // SINHALA VOWEL SIGN AELA-PILLA
    (0x0DDF, 0x0DDF),   // SINHALA VOWEL SIGN GAYANUKITTA
    (0x1160, 0x11FF),   // HANGUL JUNGSEONG FILLER .. JONGSEONG SSANGNIEUN
    (0x1715, 0x1715),   // TAGALOG SIGN PAMUDPOD
    (0x1734, 0x1734),   // HANUNOO SIGN PAMUDPOD
    (0x17A4, 0x17A4),   // KHMER INDEPENDENT VOWEL QAA (unicode-width: 2)
    (0x1ACF, 0x1ADD),   // reserved (Combining Diacritical Marks Extended)
    (0x1AE0, 0x1AEB),   // reserved (Combining Diacritical Marks Extended)
    (0x1B35, 0x1B35),   // BALINESE VOWEL SIGN TEDUNG
    (0x1B3B, 0x1B3B),   // BALINESE VOWEL SIGN RA REPA TEDUNG
    (0x1B3D, 0x1B3D),   // BALINESE VOWEL SIGN LA LENGA TEDUNG
    (0x1B43, 0x1B44),   // BALINESE VOWEL SIGN PEPET TEDUNG .. ADEG ADEG
    (0x1BAA, 0x1BAA),   // SUNDANESE SIGN PAMAAEH
    (0x1BF2, 0x1BF3),   // BATAK PANGOLAT .. PANONGONAN
    (0x2065, 0x2065),   // reserved (General Punctuation, default-ignorable)
    (0xA8FA, 0xA8FA),   // DEVANAGARI CARET
    (0xA953, 0xA953),   // REJANG VIRAMA
    (0xA9C0, 0xA9C0),   // JAVANESE PANGKON
    (0xD7B0, 0xD7C6),   // HANGUL JUNGSEONG O-YEO .. ARAEA-E
    (0xD7CB, 0xD7FB),   // HANGUL JONGSEONG NIEUN-RIEUL .. PHIEUPH-THIEUTH
    (0xFF9E, 0xFFA0),   // HALFWIDTH KATAKANA VOICED SOUND MARK .. HALFWIDTH HANGUL FILLER
    (0xFFF0, 0xFFF8),   // reserved (Specials)
    (0x10D69, 0x10D6D), // GARAY VOWEL SIGN E .. CONSONANT NASALIZATION MARK
    (0x10EFA, 0x10EFC), // reserved .. ARABIC COMBINING ALEF OVERLAY
    (0x111C0, 0x111C0), // SHARADA SIGN VIRAMA
    (0x111C2, 0x111C3), // SHARADA SIGN JIHVAMULIYA .. UPADHMANIYA
    (0x11235, 0x11235), // KHOJKI SIGN VIRAMA
    (0x1133E, 0x1133E), // GRANTHA VOWEL SIGN AA
    (0x1134D, 0x1134D), // GRANTHA SIGN VIRAMA
    (0x11357, 0x11357), // GRANTHA AU LENGTH MARK
    (0x113B8, 0x113B8), // TULU-TIGALARI VOWEL SIGN AA
    (0x113BB, 0x113C0), // TULU-TIGALARI VOWEL SIGN U .. VOCALIC LL
    (0x113C2, 0x113C2), // TULU-TIGALARI VOWEL SIGN EE
    (0x113C5, 0x113C5), // TULU-TIGALARI VOWEL SIGN AI
    (0x113C7, 0x113C9), // TULU-TIGALARI VOWEL SIGN OO .. AU LENGTH MARK
    (0x113CE, 0x113D2), // TULU-TIGALARI SIGN VIRAMA .. GEMINATION MARK
    (0x113E1, 0x113E2), // TULU-TIGALARI VEDIC TONE SVARITA .. ANUDATTA
    (0x114B0, 0x114B0), // TIRHUTA VOWEL SIGN AA
    (0x114BD, 0x114BD), // TIRHUTA VOWEL SIGN SHORT O
    (0x115AF, 0x115AF), // SIDDHAM VOWEL SIGN AA
    (0x116B6, 0x116B6), // TAKRI SIGN VIRAMA
    (0x11930, 0x11930), // DIVES AKURU VOWEL SIGN AA
    (0x1193D, 0x1193D), // DIVES AKURU SIGN HALANTA
    (0x1193F, 0x1193F), // DIVES AKURU PREFIXED NASAL SIGN
    (0x11941, 0x11941), // DIVES AKURU INITIAL RA
    (0x11A84, 0x11A89), // SOYOMBO SIGN JIHVAMULIYA .. CLUSTER-INITIAL LETTER SA
    (0x11B60, 0x11B60), // reserved (Devanagari Extended-A)
    (0x11B62, 0x11B64), // reserved (Devanagari Extended-A)
    (0x11B66, 0x11B66), // reserved (Devanagari Extended-A)
    (0x11D46, 0x11D46), // MASARAM GONDI REPHA
    (0x11F02, 0x11F02), // KAWI SIGN REPHA
    (0x11F41, 0x11F41), // KAWI SIGN KILLER
    (0x11F5A, 0x11F5A), // KAWI SIGN NUKTA
    (0x1611E, 0x16129), // GURUNG KHEMA VOWEL SIGN AA .. VOWEL LENGTH MARK
    (0x1612D, 0x1612F), // GURUNG KHEMA SIGN ANUSVARA .. THOLHOMA
    (0x1D165, 0x1D166), // MUSICAL SYMBOL COMBINING STEM .. SPRECHGESANG STEM
    (0x1D16D, 0x1D172), // MUSICAL SYMBOL COMBINING AUGMENTATION DOT .. FLAG-5
    (0x1E5EE, 0x1E5EF), // OL ONAL SIGN MU .. IKIR
    (0x1E6E3, 0x1E6E3), // reserved (Tai Yo)
    (0x1E6E6, 0x1E6E6), // reserved (Tai Yo)
    (0x1E6EE, 0x1E6EF), // reserved (Tai Yo)
    (0x1E6F5, 0x1E6F5), // reserved (Tai Yo)
    (0xE0000, 0xE0000), // reserved (Tags)
    (0xE0002, 0xE001F), // reserved (Tags)
    (0xE0080, 0xE00FF), // reserved (Tags)
    (0xE01F0, 0xE0FFF), // reserved (Tags .. Variation Selectors Supplement)
];

/// Code points displaywidth marks `_Zero_Width` but unicode-width gives a
/// non-zero width. Sorted, inclusive ranges.
const ZERO_OVERRIDES: [(u32, u32); 10] = [
    (0x0600, 0x0604),   // ARABIC NUMBER SIGN .. ARABIC SIGN SAMVAT
    (0x06DD, 0x06DD),   // ARABIC END OF AYAH
    (0x2028, 0x2029),   // LINE SEPARATOR .. PARAGRAPH SEPARATOR
    (0x2D7F, 0x2D7F),   // TIFINAGH CONSONANT JOINER
    (0xFFF9, 0xFFFB),   // INTERLINEAR ANNOTATION ANCHOR .. TERMINATOR
    (0xFFFE, 0xFFFF),   // noncharacters
    (0x110BD, 0x110BD), // KAITHI NUMBER SIGN
    (0x110CD, 0x110CD), // KAITHI NUMBER SIGN ABOVE
    (0x1171E, 0x1171E), // AHOM CONSONANT SIGN MEDIAL RA
    (0x13430, 0x1343F), // EGYPTIAN HIEROGLYPH VERTICAL JOINER .. END WALLED ENCLOSURE
];

/// The DEC ANSI parser states of x/ansi parser/const.go:41 that
/// `ansi.stringWidth` can actually occupy (`Utf8State` never persists:
/// width.go:95 resets to ground after each cluster).
#[derive(Clone, Copy, PartialEq, Eq)]
enum State {
    Ground,
    Escape,
    EscapeIntermediate,
    CsiEntry,
    CsiParam,
    CsiIntermediate,
    DcsEntry,
    DcsParam,
    DcsIntermediate,
    DcsString,
    OscString,
    SosString,
    PmString,
    ApcString,
}

/// One step of the DEC ANSI transition table
/// (x/ansi parser/transition_table.go:87 `GenerateTransitionTable`),
/// restricted to what `stringWidth` observes: the next state, and whether
/// this byte starts a printable grapheme cluster (Go's
/// `action == PrintAction || state == Utf8State`, width.go:90).
///
/// The Go table is built as blanket "anywhere" rules overridden by per-state
/// rules; the matches below encode the post-override result. Line numbers
/// refer to transition_table.go.
fn transition(state: State, b: u8) -> (State, bool) {
    use State::*;
    match state {
        Ground => match b {
            // Ground printables print (line 122) and start a grapheme
            // cluster; C0 controls execute in place (119-121, 123) via the
            // `anywhere` fallback.
            0x20..=0x7E => (Ground, true),
            _ => anywhere(b),
        },
        Escape => match b {
            0x18 | 0x1A => (Ground, false), // CAN/SUB abort (line 94)
            0x00..=0x17 | 0x19 | 0x1C..=0x1F => (Escape, false), // execute (135-137)
            0x1B => (Escape, false),        // ESC restarts (line 99)
            0x20..=0x2F => (EscapeIntermediate, false), // collect (line 147)
            0x50 => (DcsEntry, false),      // ESC P (line 153)
            0x58 => (SosString, false),     // ESC X (line 149)
            0x5B => (CsiEntry, false),      // ESC [ (line 155)
            0x5D => (OscString, false),     // ESC ] (line 157)
            0x5E => (PmString, false),      // ESC ^ (line 150)
            0x5F => (ApcString, false),     // ESC _ (line 151)
            0x30..=0x7E => (Ground, false), // dispatch (140-145)
            0x7F => (Escape, false),        // ignore (line 138)
            _ => anywhere(b),
        },
        EscapeIntermediate => match b {
            0x18 | 0x1A => (Ground, false),
            0x00..=0x17 | 0x19 | 0x1C..=0x1F => (EscapeIntermediate, false), // (126-128)
            0x1B => (Escape, false),
            0x20..=0x2F => (EscapeIntermediate, false), // collect (line 129)
            0x30..=0x7E => (Ground, false),             // dispatch (line 132)
            0x7F => (EscapeIntermediate, false),        // ignore (line 130)
            _ => anywhere(b),
        },
        CsiEntry => match b {
            0x18 | 0x1A => (Ground, false),
            0x00..=0x17 | 0x19 | 0x1C..=0x1F => (CsiEntry, false), // execute (247-249)
            0x1B => (Escape, false),
            0x20..=0x2F => (CsiIntermediate, false), // collect (line 254)
            0x30..=0x3F => (CsiParam, false),        // param/prefix (256-257)
            0x40..=0x7E => (Ground, false),          // dispatch (line 252)
            0x7F => (CsiEntry, false),               // ignore (line 250)
            _ => anywhere(b),
        },
        CsiParam => match b {
            0x18 | 0x1A => (Ground, false),
            0x00..=0x17 | 0x19 | 0x1C..=0x1F => (CsiParam, false), // execute (224-226)
            0x1B => (Escape, false),
            0x20..=0x2F => (CsiIntermediate, false), // collect (line 233)
            0x30..=0x3F => (CsiParam, false),        // param / ignore (227-229)
            0x40..=0x7E => (Ground, false),          // dispatch (line 231)
            0x7F => (CsiParam, false),               // ignore (line 228)
            _ => anywhere(b),
        },
        CsiIntermediate => match b {
            0x18 | 0x1A => (Ground, false),
            0x00..=0x17 | 0x19 | 0x1C..=0x1F => (CsiIntermediate, false), // (236-238)
            0x1B => (Escape, false),
            0x20..=0x2F => (CsiIntermediate, false), // collect (line 239)
            0x30..=0x3F => (Ground, false),          // ignore -> ground (line 244)
            0x40..=0x7E => (Ground, false),          // dispatch (line 242)
            0x7F => (CsiIntermediate, false),        // ignore (line 240)
            _ => anywhere(b),
        },
        DcsEntry => match b {
            0x18 | 0x1A => (Ground, false),
            0x08..=0x0D => (DcsString, false), // put, ECMA-48 8.3.27 (line 183)
            0x00..=0x07 | 0x0E..=0x17 | 0x19 | 0x1C..=0x1F => (DcsEntry, false), // (172-175)
            0x1B => (DcsString, false),        // ESC passthrough quirk (line 186)
            0x20..=0x2F => (DcsIntermediate, false), // collect (line 178)
            0x30..=0x3F => (DcsParam, false),  // param/prefix (180-181)
            0x40..=0x7E => (DcsString, false), // start (line 187)
            0x7F => (DcsEntry, false),         // ignore (line 176)
            _ => anywhere(b),
        },
        DcsParam => match b {
            0x18 | 0x1A => (Ground, false),
            0x00..=0x17 | 0x19 | 0x1C..=0x1F => (DcsParam, false), // ignore (200-202)
            0x1B => (Escape, false),
            0x20..=0x2F => (DcsIntermediate, false), // collect (line 207)
            0x30..=0x3F => (DcsParam, false),        // param / ignore (203-205)
            0x40..=0x7E => (DcsString, false),       // start (line 209)
            0x7F => (DcsParam, false),               // ignore (line 204)
            _ => anywhere(b),
        },
        DcsIntermediate => match b {
            0x18 | 0x1A => (Ground, false),
            0x00..=0x17 | 0x19 | 0x1C..=0x1F => (DcsIntermediate, false), // (190-192)
            0x1B => (Escape, false),
            0x20..=0x2F => (DcsIntermediate, false), // collect (line 193)
            0x30..=0x7E => (DcsString, false),       // start (196-197)
            0x7F => (DcsIntermediate, false),        // ignore (line 194)
            _ => anywhere(b),
        },
        DcsString => match b {
            0x18 | 0x1A => (Ground, false), // abort (line 221)
            0x1B => (Escape, false),        // dispatch via ESC (line 219)
            0x9C => (Ground, false),        // raw ST byte terminates (line 220)
            // Everything else is put/consumed, including 0x80..=0xFF so DCS
            // bodies may carry UTF-8 (line 217).
            _ => (DcsString, false),
        },
        OscString => match b {
            0x18 | 0x1A => (Ground, false), // abort (line 270)
            0x07 => (Ground, false),        // BEL terminates (line 268)
            0x1B => (Escape, false),        // dispatch via ESC (line 267)
            0x9C => (Ground, false),        // raw ST byte terminates (line 269)
            // 0x20..=0xFF are put (line 264), remaining C0 ignored (260-263).
            _ => (OscString, false),
        },
        SosString | PmString | ApcString => match b {
            0x18 | 0x1A => (Ground, false), // abort (line 168)
            0x1B => (Escape, false),        // dispatch via ESC (line 166)
            // Only 0x00..=0x7F are put (lines 161-164); high bytes fall
            // through to the blanket "anywhere" rules, so UTF-8 content
            // inside SOS/PM/APC leaks out as printable clusters.
            0x00..=0x7F => (state, false),
            _ => anywhere(b),
        },
    }
}

/// The blanket "anywhere" transitions (transition_table.go:91-116) for bytes
/// no per-state rule overrides: ESC restarts a sequence, C1 controls execute
/// or open sequences, UTF-8 lead bytes enter `Utf8State` (a cluster starts),
/// and everything else falls back to ground (the table default, line 89 —
/// this includes C0 executes in states whose own rules cover 0x00..=0x17,
/// 0x19, 0x1C..=0x1F but deliberately leave 0x18/0x1A/0x1B to these rules).
///
/// In a valid `&str`, raw 0x80..=0xBF bytes are only ever fed here mid-char
/// (e.g. after the OSC 0x9C-terminator quirk); matching Go means treating
/// them as C1 controls all the same.
fn anywhere(b: u8) -> (State, bool) {
    match b {
        0x1B => (State::Escape, false),       // ESC (line 99)
        0x90 => (State::DcsEntry, false),     // C1 DCS (line 109)
        0x98 => (State::SosString, false),    // C1 SOS (line 101)
        0x9B => (State::CsiEntry, false),     // C1 CSI (line 107)
        0x9D => (State::OscString, false),    // C1 OSC (line 111)
        0x9E => (State::PmString, false),     // C1 PM (line 103)
        0x9F => (State::ApcString, false),    // C1 APC (line 105)
        0xC2..=0xF4 => (State::Ground, true), // UTF-8 lead: cluster (113-115)
        _ => (State::Ground, false),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Differential tables generated from the exact Go chain leet uses, by a
    // throwaway oracle at core/tmpwidthdump/main.go (not kept in tree). To
    // regenerate, recreate it as below, plus a `corpus` []string holding the
    // strings of GO_WIDTH_CORPUS, and run from core/ (Go 1.26, vendored
    // charm.land/lipgloss/v2 v2.0.5):
    //
    //   go run -mod=vendor ./tmpwidthdump corpus   # width<TAB>escaped-string
    //   go run -mod=vendor ./tmpwidthdump single   # runs: lo hi width
    //   go run -mod=vendor ./tmpwidthdump vs16     # runs for "<cp>\u{FE0F}"
    //
    //   package main
    //   import ("bufio"; "fmt"; "os"; lipgloss "charm.land/lipgloss/v2")
    //   func main() {
    //       w := bufio.NewWriter(os.Stdout); defer w.Flush()
    //       f := func(cp rune) string { return string(cp) }
    //       if os.Args[1] == "vs16" { f = func(cp rune) string { return string(cp) + "\uFE0F" } }
    //       runStart, prev := rune(0), rune(0)
    //       runWidth := lipgloss.Width(f(0))
    //       for cp := rune(1); cp <= 0x10FFFF; cp++ {
    //           if cp >= 0xD800 && cp <= 0xDFFF { continue }
    //           if width := lipgloss.Width(f(cp)); width != runWidth {
    //               fmt.Fprintf(w, "%04X %04X %d\n", runStart, prev, runWidth)
    //               runStart, runWidth = cp, width
    //           }
    //           prev = cp
    //       }
    //       fmt.Fprintf(w, "%04X %04X %d\n", runStart, prev, runWidth)
    //   }

    /// `lipgloss.Width` per corpus string, straight from the Go oracle's
    /// `corpus` mode output.
    #[rustfmt::skip]
    const GO_WIDTH_CORPUS: &[(usize, &str)] = &[
        (0, ""),
        (1, "a"),
        (13, "Hello, World!"),
        (24, "  leading and trailing  "),
        (2, "a\tb"),
        (2, "\ta\tb\t"),
        (2, "a\u{7}b"),
        (2, "a\u{7F}b"),
        (2, "a\rb"),
        (0, "\r\n"),
        (2, "a\u{0}b"),
        (11, "─│┌┐└┘├┤┬┴┼"),
        (6, "═║╔╗╝╚"),
        (4, "╭╮╰╯"),
        (1, "⣿"),
        (8, "⠁⠂⠄⡀⢀⠈⠐⠠"),
        (4, "⡇⢸⣀⠉"),
        (1, "█"),
        (8, "▁▂▃▄▅▆▇█"),
        (7, "▀▄▌▐░▒▓"),
        (6, "▖▗▘▝▚▞"),
        (6, "日本語"),
        (4, "中文"),
        (10, "漢字テスト"),
        (5, "ｱｲｳｴｵ"),
        (12, "ＡＢＣ１２３"),
        (12, "。、「」（）"),
        (6, "한국어"),
        (2, "한"),
        (2, "ᄒ\u{1161}\u{11AB}"),
        (1, "\u{1161}"),
        (1, "\u{11AB}"),
        (2, "😀"),
        (2, "🚀"),
        (2, "🎉"),
        (2, "🤖"),
        (2, "👩\u{200D}🚀"),
        (2, "👨\u{200D}👩\u{200D}👧\u{200D}👦"),
        (2, "🏷\u{FE0F}"),
        (1, "🏷"),
        (2, "🏳\u{FE0F}\u{200D}🌈"),
        (2, "🇺🇸"),
        (2, "🇯🇵"),
        (2, "🇺"),
        (4, "🇺🇸🇯"),
        (2, "👍🏽"),
        (2, "🏽"),
        (2, "1\u{FE0F}\u{20E3}"),
        (1, "#\u{20E3}"),
        (2, "❤\u{FE0F}"),
        (1, "❤"),
        (1, "❤\u{FE0E}"),
        (2, "☂\u{FE0F}"),
        (2, "✔\u{FE0F}"),
        (1, "✔"),
        (2, "©\u{FE0F}"),
        (1, "©"),
        (2, "A\u{FE0F}"),
        (2, "±\u{FE0F}"),
        (2, "0\u{FE0F}"),
        (2, "日\u{FE0F}"),
        (1, "é"),
        (1, "e\u{301}"),
        (1, "n\u{303}"),
        (0, "\u{301}"),
        (1, "a\u{308}\u{301}"),
        (3, "नमस्ते"),
        (1, "क्षि"),
        (0, "\u{200B}"),
        (2, "a\u{200B}b"),
        (0, "\u{200D}"),
        (0, "\u{200C}"),
        (0, "\u{FEFF}"),
        (0, "\u{AD}"),
        (2, "a\u{AD}b"),
        (0, "\u{85}"),
        (0, "\u{9B}"),
        (2, "a\u{85}b"),
        (5, "±×÷°·"),
        (5, "αβγΩπ"),
        (6, "Привет"),
        (3, "£§¶"),
        (4, "→←↑↓"),
        (2, "★☆"),
        (3, "①②③"),
        (1, "Ⅷ"),
        (2, "…‰"),
        (1, "€"),
        (2, "✓✗"),
        (4, "▲△▶▷"),
        (4, "♠♥♦♣"),
        (20, "日本語ラン 🚀 家族👨\u{200D}👩\u{200D}👧\u{200D}👦"),
        (58, "多言語ノート: emoji 🎉, ZWJ 👩\u{200D}🚀, combining café, 中文注释。"),
        (4, "标签"),
        (5, "🏷\u{FE0F}tag"),
        (6, "ラベル"),
        (4, "café"),
        (4, "描述"),
        (9, "模型/名字"),
        (10, "变形金刚🤖"),
        (23, "训练开始 🚀 ログ出力 👨\u{200D}👩\u{200D}👧\u{200D}👦\n"),
        (13, "emoji/🚀speed"),
        (9, "损失/loss"),
        (11, "short\nlonger line"),
        (6, "日本語\nab"),
        (0, "\n"),
        (1, "a\n"),
        (1, "\na"),
        (7, "one\ntwo\nthree33"),
        (3, "\u{1B}[31mred\u{1B}[0m"),
        (4, "\u{1B}[1;38;5;196mbold\u{1B}[m"),
        (6, "\u{1B}[38;2;255;0;0m日本語\u{1B}[0m"),
        (4, "\u{1B}]8;;https://x.com\u{7}link\u{1B}]8;;\u{7}"),
        (4, "\u{1B}]0;title\u{1B}\\text"),
        (0, "\u{1B}[31"),
        (3, "abc\u{1B}"),
        (5, "\u{1B}(Bhello"),
        (1, "\u{1B}[3\u{18}m"),
        (3, "\u{1B}[31日m"),
        (2, "\u{1B}]0;aŜb\u{7}x"),
        (3, "\u{1B}Xhidden\u{1B}\\end"),
        (5, "\u{1B}Xab日cd\u{1B}\\e"),
        (5, "\u{1B}P1;2qpayload\u{1B}\\after"),
        (2, "\u{1B}_Gdata\u{1B}\\ok"),
        (0, "\u{1B}[0m"),
        (0, "\u{1B}[m"),
        (22, "loss: 0.123 │ acc: 98%"),
        (17, "run-😀-日本 [1/3]"),
        (18, "▶ Träume 🇩🇪 — Ω≈2π"),
        (20, "sys/gpu.0.memory (%)"),
        (3, "‖⁇⁈"),
    ];

    #[test]
    fn corpus_matches_go() {
        for &(want, s) in GO_WIDTH_CORPUS {
            assert_eq!(text_width(s), want, "text_width({s:?})");
        }
    }

    /// Go `lipgloss.Width(string(cp))` for every Unicode scalar value,
    /// run-length encoded as `lo-hi:width` (hex, inclusive).
    const GO_SINGLE_SCALAR_RUNS: &str = r#"
0000-001F:0 0020-007E:1 007F-009F:0 00A0-00AC:1 00AD-00AD:0 00AE-02FF:1 0300-036F:0 0370-0482:1
0483-0489:0 048A-0590:1 0591-05BD:0 05BE-05BE:1 05BF-05BF:0 05C0-05C0:1 05C1-05C2:0 05C3-05C3:1
05C4-05C5:0 05C6-05C6:1 05C7-05C7:0 05C8-05FF:1 0600-0605:0 0606-060F:1 0610-061A:0 061B-061B:1
061C-061C:0 061D-064A:1 064B-065F:0 0660-066F:1 0670-0670:0 0671-06D5:1 06D6-06DD:0 06DE-06DE:1
06DF-06E4:0 06E5-06E6:1 06E7-06E8:0 06E9-06E9:1 06EA-06ED:0 06EE-070E:1 070F-070F:0 0710-0710:1
0711-0711:0 0712-072F:1 0730-074A:0 074B-07A5:1 07A6-07B0:0 07B1-07EA:1 07EB-07F3:0 07F4-07FC:1
07FD-07FD:0 07FE-0815:1 0816-0819:0 081A-081A:1 081B-0823:0 0824-0824:1 0825-0827:0 0828-0828:1
0829-082D:0 082E-0858:1 0859-085B:0 085C-088F:1 0890-0891:0 0892-0897:1 0898-089F:0 08A0-08C9:1
08CA-0902:0 0903-0939:1 093A-093A:0 093B-093B:1 093C-093C:0 093D-0940:1 0941-0948:0 0949-094C:1
094D-094D:0 094E-0950:1 0951-0957:0 0958-0961:1 0962-0963:0 0964-0980:1 0981-0981:0 0982-09BB:1
09BC-09BC:0 09BD-09C0:1 09C1-09C4:0 09C5-09CC:1 09CD-09CD:0 09CE-09E1:1 09E2-09E3:0 09E4-09FD:1
09FE-09FE:0 09FF-0A00:1 0A01-0A02:0 0A03-0A3B:1 0A3C-0A3C:0 0A3D-0A40:1 0A41-0A42:0 0A43-0A46:1
0A47-0A48:0 0A49-0A4A:1 0A4B-0A4D:0 0A4E-0A50:1 0A51-0A51:0 0A52-0A6F:1 0A70-0A71:0 0A72-0A74:1
0A75-0A75:0 0A76-0A80:1 0A81-0A82:0 0A83-0ABB:1 0ABC-0ABC:0 0ABD-0AC0:1 0AC1-0AC5:0 0AC6-0AC6:1
0AC7-0AC8:0 0AC9-0ACC:1 0ACD-0ACD:0 0ACE-0AE1:1 0AE2-0AE3:0 0AE4-0AF9:1 0AFA-0AFF:0 0B00-0B00:1
0B01-0B01:0 0B02-0B3B:1 0B3C-0B3C:0 0B3D-0B3E:1 0B3F-0B3F:0 0B40-0B40:1 0B41-0B44:0 0B45-0B4C:1
0B4D-0B4D:0 0B4E-0B54:1 0B55-0B56:0 0B57-0B61:1 0B62-0B63:0 0B64-0B81:1 0B82-0B82:0 0B83-0BBF:1
0BC0-0BC0:0 0BC1-0BCC:1 0BCD-0BCD:0 0BCE-0BFF:1 0C00-0C00:0 0C01-0C03:1 0C04-0C04:0 0C05-0C3B:1
0C3C-0C3C:0 0C3D-0C3D:1 0C3E-0C40:0 0C41-0C45:1 0C46-0C48:0 0C49-0C49:1 0C4A-0C4D:0 0C4E-0C54:1
0C55-0C56:0 0C57-0C61:1 0C62-0C63:0 0C64-0C80:1 0C81-0C81:0 0C82-0CBB:1 0CBC-0CBC:0 0CBD-0CBE:1
0CBF-0CBF:0 0CC0-0CC5:1 0CC6-0CC6:0 0CC7-0CCB:1 0CCC-0CCD:0 0CCE-0CE1:1 0CE2-0CE3:0 0CE4-0CFF:1
0D00-0D01:0 0D02-0D3A:1 0D3B-0D3C:0 0D3D-0D40:1 0D41-0D44:0 0D45-0D4C:1 0D4D-0D4D:0 0D4E-0D61:1
0D62-0D63:0 0D64-0D80:1 0D81-0D81:0 0D82-0DC9:1 0DCA-0DCA:0 0DCB-0DD1:1 0DD2-0DD4:0 0DD5-0DD5:1
0DD6-0DD6:0 0DD7-0E30:1 0E31-0E31:0 0E32-0E33:1 0E34-0E3A:0 0E3B-0E46:1 0E47-0E4E:0 0E4F-0EB0:1
0EB1-0EB1:0 0EB2-0EB3:1 0EB4-0EBC:0 0EBD-0EC7:1 0EC8-0ECE:0 0ECF-0F17:1 0F18-0F19:0 0F1A-0F34:1
0F35-0F35:0 0F36-0F36:1 0F37-0F37:0 0F38-0F38:1 0F39-0F39:0 0F3A-0F70:1 0F71-0F7E:0 0F7F-0F7F:1
0F80-0F84:0 0F85-0F85:1 0F86-0F87:0 0F88-0F8C:1 0F8D-0F97:0 0F98-0F98:1 0F99-0FBC:0 0FBD-0FC5:1
0FC6-0FC6:0 0FC7-102C:1 102D-1030:0 1031-1031:1 1032-1037:0 1038-1038:1 1039-103A:0 103B-103C:1
103D-103E:0 103F-1057:1 1058-1059:0 105A-105D:1 105E-1060:0 1061-1070:1 1071-1074:0 1075-1081:1
1082-1082:0 1083-1084:1 1085-1086:0 1087-108C:1 108D-108D:0 108E-109C:1 109D-109D:0 109E-10FF:1
1100-115F:2 1160-135C:1 135D-135F:0 1360-1711:1 1712-1714:0 1715-1731:1 1732-1733:0 1734-1751:1
1752-1753:0 1754-1771:1 1772-1773:0 1774-17B3:1 17B4-17B5:0 17B6-17B6:1 17B7-17BD:0 17BE-17C5:1
17C6-17C6:0 17C7-17C8:1 17C9-17D3:0 17D4-17DC:1 17DD-17DD:0 17DE-180A:1 180B-180F:0 1810-1884:1
1885-1886:0 1887-18A8:1 18A9-18A9:0 18AA-191F:1 1920-1922:0 1923-1926:1 1927-1928:0 1929-1931:1
1932-1932:0 1933-1938:1 1939-193B:0 193C-1A16:1 1A17-1A18:0 1A19-1A1A:1 1A1B-1A1B:0 1A1C-1A55:1
1A56-1A56:0 1A57-1A57:1 1A58-1A5E:0 1A5F-1A5F:1 1A60-1A60:0 1A61-1A61:1 1A62-1A62:0 1A63-1A64:1
1A65-1A6C:0 1A6D-1A72:1 1A73-1A7C:0 1A7D-1A7E:1 1A7F-1A7F:0 1A80-1AAF:1 1AB0-1ACE:0 1ACF-1AFF:1
1B00-1B03:0 1B04-1B33:1 1B34-1B34:0 1B35-1B35:1 1B36-1B3A:0 1B3B-1B3B:1 1B3C-1B3C:0 1B3D-1B41:1
1B42-1B42:0 1B43-1B6A:1 1B6B-1B73:0 1B74-1B7F:1 1B80-1B81:0 1B82-1BA1:1 1BA2-1BA5:0 1BA6-1BA7:1
1BA8-1BA9:0 1BAA-1BAA:1 1BAB-1BAD:0 1BAE-1BE5:1 1BE6-1BE6:0 1BE7-1BE7:1 1BE8-1BE9:0 1BEA-1BEC:1
1BED-1BED:0 1BEE-1BEE:1 1BEF-1BF1:0 1BF2-1C2B:1 1C2C-1C33:0 1C34-1C35:1 1C36-1C37:0 1C38-1CCF:1
1CD0-1CD2:0 1CD3-1CD3:1 1CD4-1CE0:0 1CE1-1CE1:1 1CE2-1CE8:0 1CE9-1CEC:1 1CED-1CED:0 1CEE-1CF3:1
1CF4-1CF4:0 1CF5-1CF7:1 1CF8-1CF9:0 1CFA-1DBF:1 1DC0-1DFF:0 1E00-200A:1 200B-200F:0 2010-2027:1
2028-202E:0 202F-205F:1 2060-2064:0 2065-2065:1 2066-206F:0 2070-20CF:1 20D0-20F0:0 20F1-2319:1
231A-231B:2 231C-2328:1 2329-232A:2 232B-23E8:1 23E9-23EC:2 23ED-23EF:1 23F0-23F0:2 23F1-23F2:1
23F3-23F3:2 23F4-25FC:1 25FD-25FE:2 25FF-2613:1 2614-2615:2 2616-262F:1 2630-2637:2 2638-2647:1
2648-2653:2 2654-267E:1 267F-267F:2 2680-2689:1 268A-268F:2 2690-2692:1 2693-2693:2 2694-26A0:1
26A1-26A1:2 26A2-26A9:1 26AA-26AB:2 26AC-26BC:1 26BD-26BE:2 26BF-26C3:1 26C4-26C5:2 26C6-26CD:1
26CE-26CE:2 26CF-26D3:1 26D4-26D4:2 26D5-26E9:1 26EA-26EA:2 26EB-26F1:1 26F2-26F3:2 26F4-26F4:1
26F5-26F5:2 26F6-26F9:1 26FA-26FA:2 26FB-26FC:1 26FD-26FD:2 26FE-2704:1 2705-2705:2 2706-2709:1
270A-270B:2 270C-2727:1 2728-2728:2 2729-274B:1 274C-274C:2 274D-274D:1 274E-274E:2 274F-2752:1
2753-2755:2 2756-2756:1 2757-2757:2 2758-2794:1 2795-2797:2 2798-27AF:1 27B0-27B0:2 27B1-27BE:1
27BF-27BF:2 27C0-2B1A:1 2B1B-2B1C:2 2B1D-2B4F:1 2B50-2B50:2 2B51-2B54:1 2B55-2B55:2 2B56-2CEE:1
2CEF-2CF1:0 2CF2-2D7E:1 2D7F-2D7F:0 2D80-2DDF:1 2DE0-2DFF:0 2E00-2E7F:1 2E80-2E99:2 2E9A-2E9A:1
2E9B-2EF3:2 2EF4-2EFF:1 2F00-2FD5:2 2FD6-2FEF:1 2FF0-3029:2 302A-302D:0 302E-303E:2 303F-3040:1
3041-3096:2 3097-3098:1 3099-309A:0 309B-30FF:2 3100-3104:1 3105-312F:2 3130-3130:1 3131-318E:2
318F-318F:1 3190-31E5:2 31E6-31EE:1 31EF-321E:2 321F-321F:1 3220-3247:2 3248-324F:1 3250-A48C:2
A48D-A48F:1 A490-A4C6:2 A4C7-A66E:1 A66F-A672:0 A673-A673:1 A674-A67D:0 A67E-A69D:1 A69E-A69F:0
A6A0-A6EF:1 A6F0-A6F1:0 A6F2-A801:1 A802-A802:0 A803-A805:1 A806-A806:0 A807-A80A:1 A80B-A80B:0
A80C-A824:1 A825-A826:0 A827-A82B:1 A82C-A82C:0 A82D-A8C3:1 A8C4-A8C5:0 A8C6-A8DF:1 A8E0-A8F1:0
A8F2-A8FE:1 A8FF-A8FF:0 A900-A925:1 A926-A92D:0 A92E-A946:1 A947-A951:0 A952-A95F:1 A960-A97C:2
A97D-A97F:1 A980-A982:0 A983-A9B2:1 A9B3-A9B3:0 A9B4-A9B5:1 A9B6-A9B9:0 A9BA-A9BB:1 A9BC-A9BD:0
A9BE-A9E4:1 A9E5-A9E5:0 A9E6-AA28:1 AA29-AA2E:0 AA2F-AA30:1 AA31-AA32:0 AA33-AA34:1 AA35-AA36:0
AA37-AA42:1 AA43-AA43:0 AA44-AA4B:1 AA4C-AA4C:0 AA4D-AA7B:1 AA7C-AA7C:0 AA7D-AAAF:1 AAB0-AAB0:0
AAB1-AAB1:1 AAB2-AAB4:0 AAB5-AAB6:1 AAB7-AAB8:0 AAB9-AABD:1 AABE-AABF:0 AAC0-AAC0:1 AAC1-AAC1:0
AAC2-AAEB:1 AAEC-AAED:0 AAEE-AAF5:1 AAF6-AAF6:0 AAF7-ABE4:1 ABE5-ABE5:0 ABE6-ABE7:1 ABE8-ABE8:0
ABE9-ABEC:1 ABED-ABED:0 ABEE-ABFF:1 AC00-D7A3:2 D7A4-F8FF:1 F900-FAFF:2 FB00-FB1D:1 FB1E-FB1E:0
FB1F-FDFF:1 FE00-FE0F:0 FE10-FE19:2 FE1A-FE1F:1 FE20-FE2F:0 FE30-FE52:2 FE53-FE53:1 FE54-FE66:2
FE67-FE67:1 FE68-FE6B:2 FE6C-FEFE:1 FEFF-FEFF:0 FF00-FF00:1 FF01-FF60:2 FF61-FFDF:1 FFE0-FFE6:2
FFE7-FFF8:1 FFF9-FFFB:0 FFFC-FFFD:1 FFFE-FFFF:0 10000-101FC:1 101FD-101FD:0 101FE-102DF:1
102E0-102E0:0 102E1-10375:1 10376-1037A:0 1037B-10A00:1 10A01-10A03:0 10A04-10A04:1
10A05-10A06:0 10A07-10A0B:1 10A0C-10A0F:0 10A10-10A37:1 10A38-10A3A:0 10A3B-10A3E:1
10A3F-10A3F:0 10A40-10AE4:1 10AE5-10AE6:0 10AE7-10D23:1 10D24-10D27:0 10D28-10EAA:1
10EAB-10EAC:0 10EAD-10EFC:1 10EFD-10EFF:0 10F00-10F45:1 10F46-10F50:0 10F51-10F81:1
10F82-10F85:0 10F86-11000:1 11001-11001:0 11002-11037:1 11038-11046:0 11047-1106F:1
11070-11070:0 11071-11072:1 11073-11074:0 11075-1107E:1 1107F-11081:0 11082-110B2:1
110B3-110B6:0 110B7-110B8:1 110B9-110BA:0 110BB-110BC:1 110BD-110BD:0 110BE-110C1:1
110C2-110C2:0 110C3-110CC:1 110CD-110CD:0 110CE-110FF:1 11100-11102:0 11103-11126:1
11127-1112B:0 1112C-1112C:1 1112D-11134:0 11135-11172:1 11173-11173:0 11174-1117F:1
11180-11181:0 11182-111B5:1 111B6-111BE:0 111BF-111C8:1 111C9-111CC:0 111CD-111CE:1
111CF-111CF:0 111D0-1122E:1 1122F-11231:0 11232-11233:1 11234-11234:0 11235-11235:1
11236-11237:0 11238-1123D:1 1123E-1123E:0 1123F-11240:1 11241-11241:0 11242-112DE:1
112DF-112DF:0 112E0-112E2:1 112E3-112EA:0 112EB-112FF:1 11300-11301:0 11302-1133A:1
1133B-1133C:0 1133D-1133F:1 11340-11340:0 11341-11365:1 11366-1136C:0 1136D-1136F:1
11370-11374:0 11375-11437:1 11438-1143F:0 11440-11441:1 11442-11444:0 11445-11445:1
11446-11446:0 11447-1145D:1 1145E-1145E:0 1145F-114B2:1 114B3-114B8:0 114B9-114B9:1
114BA-114BA:0 114BB-114BE:1 114BF-114C0:0 114C1-114C1:1 114C2-114C3:0 114C4-115B1:1
115B2-115B5:0 115B6-115BB:1 115BC-115BD:0 115BE-115BE:1 115BF-115C0:0 115C1-115DB:1
115DC-115DD:0 115DE-11632:1 11633-1163A:0 1163B-1163C:1 1163D-1163D:0 1163E-1163E:1
1163F-11640:0 11641-116AA:1 116AB-116AB:0 116AC-116AC:1 116AD-116AD:0 116AE-116AF:1
116B0-116B5:0 116B6-116B6:1 116B7-116B7:0 116B8-1171C:1 1171D-1171F:0 11720-11721:1
11722-11725:0 11726-11726:1 11727-1172B:0 1172C-1182E:1 1182F-11837:0 11838-11838:1
11839-1183A:0 1183B-1193A:1 1193B-1193C:0 1193D-1193D:1 1193E-1193E:0 1193F-11942:1
11943-11943:0 11944-119D3:1 119D4-119D7:0 119D8-119D9:1 119DA-119DB:0 119DC-119DF:1
119E0-119E0:0 119E1-11A00:1 11A01-11A0A:0 11A0B-11A32:1 11A33-11A38:0 11A39-11A3A:1
11A3B-11A3E:0 11A3F-11A46:1 11A47-11A47:0 11A48-11A50:1 11A51-11A56:0 11A57-11A58:1
11A59-11A5B:0 11A5C-11A89:1 11A8A-11A96:0 11A97-11A97:1 11A98-11A99:0 11A9A-11C2F:1
11C30-11C36:0 11C37-11C37:1 11C38-11C3D:0 11C3E-11C3E:1 11C3F-11C3F:0 11C40-11C91:1
11C92-11CA7:0 11CA8-11CA9:1 11CAA-11CB0:0 11CB1-11CB1:1 11CB2-11CB3:0 11CB4-11CB4:1
11CB5-11CB6:0 11CB7-11D30:1 11D31-11D36:0 11D37-11D39:1 11D3A-11D3A:0 11D3B-11D3B:1
11D3C-11D3D:0 11D3E-11D3E:1 11D3F-11D45:0 11D46-11D46:1 11D47-11D47:0 11D48-11D8F:1
11D90-11D91:0 11D92-11D94:1 11D95-11D95:0 11D96-11D96:1 11D97-11D97:0 11D98-11EF2:1
11EF3-11EF4:0 11EF5-11EFF:1 11F00-11F01:0 11F02-11F35:1 11F36-11F3A:0 11F3B-11F3F:1
11F40-11F40:0 11F41-11F41:1 11F42-11F42:0 11F43-1342F:1 13430-13440:0 13441-13446:1
13447-13455:0 13456-16AEF:1 16AF0-16AF4:0 16AF5-16B2F:1 16B30-16B36:0 16B37-16F4E:1
16F4F-16F4F:0 16F50-16F8E:1 16F8F-16F92:0 16F93-16FDF:1 16FE0-16FE3:2 16FE4-16FE4:0
16FE5-16FEF:1 16FF0-16FF6:2 16FF7-16FFF:1 17000-18CD5:2 18CD6-18CFE:1 18CFF-18D1E:2
18D1F-18D7F:1 18D80-18DF2:2 18DF3-1AFEF:1 1AFF0-1AFF3:2 1AFF4-1AFF4:1 1AFF5-1AFFB:2
1AFFC-1AFFC:1 1AFFD-1AFFE:2 1AFFF-1AFFF:1 1B000-1B122:2 1B123-1B131:1 1B132-1B132:2
1B133-1B14F:1 1B150-1B152:2 1B153-1B154:1 1B155-1B155:2 1B156-1B163:1 1B164-1B167:2
1B168-1B16F:1 1B170-1B2FB:2 1B2FC-1BC9C:1 1BC9D-1BC9E:0 1BC9F-1BC9F:1 1BCA0-1BCA3:0
1BCA4-1CEFF:1 1CF00-1CF2D:0 1CF2E-1CF2F:1 1CF30-1CF46:0 1CF47-1D166:1 1D167-1D169:0
1D16A-1D172:1 1D173-1D182:0 1D183-1D184:1 1D185-1D18B:0 1D18C-1D1A9:1 1D1AA-1D1AD:0
1D1AE-1D241:1 1D242-1D244:0 1D245-1D2FF:1 1D300-1D356:2 1D357-1D35F:1 1D360-1D376:2
1D377-1D9FF:1 1DA00-1DA36:0 1DA37-1DA3A:1 1DA3B-1DA6C:0 1DA6D-1DA74:1 1DA75-1DA75:0
1DA76-1DA83:1 1DA84-1DA84:0 1DA85-1DA9A:1 1DA9B-1DA9F:0 1DAA0-1DAA0:1 1DAA1-1DAAF:0
1DAB0-1DFFF:1 1E000-1E006:0 1E007-1E007:1 1E008-1E018:0 1E019-1E01A:1 1E01B-1E021:0
1E022-1E022:1 1E023-1E024:0 1E025-1E025:1 1E026-1E02A:0 1E02B-1E08E:1 1E08F-1E08F:0
1E090-1E12F:1 1E130-1E136:0 1E137-1E2AD:1 1E2AE-1E2AE:0 1E2AF-1E2EB:1 1E2EC-1E2EF:0
1E2F0-1E4EB:1 1E4EC-1E4EF:0 1E4F0-1E8CF:1 1E8D0-1E8D6:0 1E8D7-1E943:1 1E944-1E94A:0
1E94B-1F003:1 1F004-1F004:2 1F005-1F0CE:1 1F0CF-1F0CF:2 1F0D0-1F18D:1 1F18E-1F18E:2
1F18F-1F190:1 1F191-1F19A:2 1F19B-1F1E5:1 1F1E6-1F202:2 1F203-1F20F:1 1F210-1F23B:2
1F23C-1F23F:1 1F240-1F248:2 1F249-1F24F:1 1F250-1F251:2 1F252-1F25F:1 1F260-1F265:2
1F266-1F2FF:1 1F300-1F320:2 1F321-1F32C:1 1F32D-1F335:2 1F336-1F336:1 1F337-1F37C:2
1F37D-1F37D:1 1F37E-1F393:2 1F394-1F39F:1 1F3A0-1F3CA:2 1F3CB-1F3CE:1 1F3CF-1F3D3:2
1F3D4-1F3DF:1 1F3E0-1F3F0:2 1F3F1-1F3F3:1 1F3F4-1F3F4:2 1F3F5-1F3F7:1 1F3F8-1F43E:2
1F43F-1F43F:1 1F440-1F440:2 1F441-1F441:1 1F442-1F4FC:2 1F4FD-1F4FE:1 1F4FF-1F53D:2
1F53E-1F54A:1 1F54B-1F54E:2 1F54F-1F54F:1 1F550-1F567:2 1F568-1F579:1 1F57A-1F57A:2
1F57B-1F594:1 1F595-1F596:2 1F597-1F5A3:1 1F5A4-1F5A4:2 1F5A5-1F5FA:1 1F5FB-1F64F:2
1F650-1F67F:1 1F680-1F6C5:2 1F6C6-1F6CB:1 1F6CC-1F6CC:2 1F6CD-1F6CF:1 1F6D0-1F6D2:2
1F6D3-1F6D4:1 1F6D5-1F6D8:2 1F6D9-1F6DB:1 1F6DC-1F6DF:2 1F6E0-1F6EA:1 1F6EB-1F6EC:2
1F6ED-1F6F3:1 1F6F4-1F6FC:2 1F6FD-1F7DF:1 1F7E0-1F7EB:2 1F7EC-1F7EF:1 1F7F0-1F7F0:2
1F7F1-1F90B:1 1F90C-1F93A:2 1F93B-1F93B:1 1F93C-1F945:2 1F946-1F946:1 1F947-1F9FF:2
1FA00-1FA6F:1 1FA70-1FA7C:2 1FA7D-1FA7F:1 1FA80-1FA8A:2 1FA8B-1FA8D:1 1FA8E-1FAC6:2
1FAC7-1FAC7:1 1FAC8-1FAC8:2 1FAC9-1FACC:1 1FACD-1FADC:2 1FADD-1FADE:1 1FADF-1FAEA:2
1FAEB-1FAEE:1 1FAEF-1FAF8:2 1FAF9-1FFFF:1 20000-2FFFD:2 2FFFE-2FFFF:1 30000-3FFFD:2
3FFFE-E0000:1 E0001-E0001:0 E0002-E001F:1 E0020-E007F:0 E0080-E00FF:1 E0100-E01EF:0
E01F0-10FFFF:1
"#;

    /// Go `lipgloss.Width(string(cp) + "\u{FE0F}")` for every Unicode scalar
    /// value: the VS16 promotion rule and cluster joining, exhaustively.
    const GO_VS16_RUNS: &str = r#"
0000-001F:0 0020-007E:2 007F-009F:0 00A0-00AC:2 00AD-00AD:0 00AE-061B:2 061C-061C:0 061D-180D:2
180E-180E:0 180F-200A:2 200B-200B:0 200C-200D:2 200E-200F:0 2010-2027:2 2028-202E:0 202F-205F:2
2060-2064:0 2065-2065:1 2066-206F:0 2070-FEFE:2 FEFF-FEFF:0 FF00-FFEF:2 FFF0-FFF8:1 FFF9-FFFB:0
FFFC-1342F:2 13430-1343F:0 13440-1BC9F:2 1BCA0-1BCA3:0 1BCA4-1D172:2 1D173-1D17A:0 1D17B-DFFFF:2
E0000-E0000:1 E0001-E0001:0 E0002-E001F:1 E0020-E007F:2 E0080-E00FF:1 E0100-E01EF:2
E01F0-E0FFF:1 E1000-10FFFF:2
"#;

    fn assert_sweep_matches(runs: &str, f: impl Fn(char) -> String) {
        let mut checked = 0u32;
        for tok in runs.split_whitespace() {
            let (range, w) = tok.split_once(':').expect("run token");
            let (lo, hi) = range.split_once('-').expect("run range");
            let lo = u32::from_str_radix(lo, 16).unwrap();
            let hi = u32::from_str_radix(hi, 16).unwrap();
            let want = w.parse::<usize>().unwrap();
            for cp in lo..=hi {
                let Some(c) = char::from_u32(cp) else {
                    continue; // surrogates
                };
                assert_eq!(text_width(&f(c)), want, "U+{cp:04X}");
                checked += 1;
            }
        }
        assert_eq!(checked, 0x110000 - 0x800); // all scalars covered
    }

    #[test]
    fn single_scalar_sweep_matches_go() {
        assert_sweep_matches(GO_SINGLE_SCALAR_RUNS, |c| c.to_string());
    }

    #[test]
    fn vs16_sweep_matches_go() {
        assert_sweep_matches(GO_VS16_RUNS, |c| format!("{c}\u{FE0F}"));
    }

    #[test]
    fn line_width_counts_all_lines_unlike_text_width() {
        // ansi.StringWidth itself does not split on newlines: \n is a C0
        // control (Execute, width 0), so "a\nbb" measures 3 in one call,
        // while lipgloss.Width takes the max line (2).
        assert_eq!(line_width("a\nbb"), 3);
        assert_eq!(text_width("a\nbb"), 2);
    }

    #[test]
    fn grapheme_width_matches_go_cluster_rules() {
        assert_eq!(grapheme_width(""), 0);
        assert_eq!(grapheme_width("a"), 1);
        assert_eq!(grapheme_width("\u{7}"), 0); // asciiWidth: C0
        assert_eq!(grapheme_width("\u{7F}"), 0); // asciiWidth: DEL
        assert_eq!(grapheme_width("\r\n"), 0); // C0-led multi-byte cluster
        assert_eq!(grapheme_width("e\u{301}"), 1); // width of first cp
        assert_eq!(
            grapheme_width("\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}\u{200D}\u{1F466}"),
            2
        );
        assert_eq!(grapheme_width("\u{1F1FA}\u{1F1F8}"), 2); // RI pair
        assert_eq!(grapheme_width("A\u{FE0F}"), 2); // VS16 promotes any base
        assert_eq!(grapheme_width("\u{65E5}\u{FE0F}"), 2); // wide stays wide
        assert_eq!(grapheme_width("\u{2764}\u{FE0E}"), 1); // VS15: no effect
    }
}
