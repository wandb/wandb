//! Port of `core/internal/terminalemulator` (`terminalemulator.go` +
//! `lines.go`): a virtual terminal that supports common ANSI / xterm escape
//! sequences.
//!
//! For a list of various sequences and their definitions, see
//! <https://xfree86.org/4.8.0/ctlseqs.html>. This isn't a full terminal
//! emulator, so most sequences aren't supported, but support can be added for
//! any sequence as necessary for W&B. Primarily, we need to support cursor
//! operations which are used by `tqdm`-style progress bars.
//!
//! For a great history and overview of terminals, see
//! <https://gpanders.com/blog/state-of-the-terminal/>

/// LineSupplier returns lines for a terminal emulator to use.
pub trait LineSupplier {
    /// Returns a new line below the previous ones.
    fn next_line(&mut self) -> Box<dyn Line>;
}

/// Line is a line of text that a terminal emulator modifies.
pub trait Line {
    /// Modifies the line's contents.
    fn put_char(&mut self, c: char, offset: usize);
}

/// LineContent is a mutable string with a bound on its length.
///
/// This may be used to back a [`Line`] implementation.
// PARITY: Go's LineContent.Clone() (a deep copy via slices.Clone) is the
// derived Clone here.
#[derive(Debug, Clone, Default)]
pub struct LineContent {
    /// The maximum number of runes in the line.
    pub max_length: usize,

    /// The text on the line.
    pub content: Vec<char>,
}

impl LineContent {
    /// Returns a copy of the line's current content.
    pub fn content_as_string(&self) -> String {
        self.content.iter().collect()
    }

    /// Updates the line and returns whether it was modified.
    pub fn put_char(&mut self, c: char, offset: usize) -> bool {
        if offset >= self.max_length {
            return false;
        }

        while offset >= self.content.len() {
            self.content.push(' ');
        }

        if self.content[offset] == c {
            return false;
        }

        self.content[offset] = c;
        true
    }
}

/// Terminal is a text buffer that processes escape sequences.
///
/// This class is not safe for concurrent use and must be externally
/// synchronized.
// PARITY: the Go int cursor fields port as usize — viewX/viewY never go
// negative: cursorUp guards viewY > 0, and scrollDown is only reached right
// after an increment (see scroll_down).
pub struct Terminal {
    /// Creates lines for the terminal to use.
    line_supplier: Box<dyn LineSupplier>,

    /// The number of lines in the terminal's view area.
    height: usize,

    /// The list of lines in the terminal.
    view: Vec<Box<dyn Line>>,

    /// The cursor's Y position in the view.
    ///
    /// It is an index into the view slice. 0 is the top line in the view.
    view_y: usize,

    /// The cursor's X position in the view.
    view_x: usize,

    /// The accumulated escape sequence.
    ///
    /// This is the empty string if we're not parsing an escape sequence.
    escape_sequence: String,
}

impl Terminal {
    /// Returns an empty terminal.
    pub fn new(line_supplier: Box<dyn LineSupplier>, height: usize) -> Self {
        Terminal {
            line_supplier,
            height,
            view: Vec::new(),
            view_y: 0,
            view_x: 0,
            escape_sequence: String::new(),
        }
    }

    /// Sends input to the terminal.
    pub fn write(&mut self, input: &str) {
        for char in input.chars() {
            match self.escape_sequence.as_str() {
                "" => match char {
                    '\r' => self.carriage_return(),
                    '\n' => self.line_feed(),
                    '\x1b' => self.escape_sequence = String::from(char),
                    _ => self.put_char(char),
                },

                "\x1b" => match char {
                    '[' => self.escape_sequence = "\x1b[".to_string(),
                    _ => {
                        self.print_escape_sequence();
                        self.put_char(char);
                    }
                },

                "\x1b[" => match char {
                    'A' => {
                        self.cursor_up();
                        self.escape_sequence.clear();
                    }
                    'B' => {
                        self.cursor_down();
                        self.escape_sequence.clear();
                    }
                    _ => {
                        self.print_escape_sequence();
                        self.put_char(char);
                    }
                },

                // PARITY: unreachable — escape_sequence only ever holds "",
                // "\x1b" or "\x1b[" (Go's switch has no other cases either).
                _ => unreachable!("invalid escape sequence state"),
            }
        }
    }

    /// Prints out and resets the accumulated escape sequence.
    ///
    /// This is used for unknown escape sequences.
    fn print_escape_sequence(&mut self) {
        // PARITY: Go clears escapeSequence after the loop; put_char never
        // reads it, so taking it up front is observably identical.
        let escape_sequence = std::mem::take(&mut self.escape_sequence);
        for char in escape_sequence.chars() {
            self.put_char(char);
        }
    }

    /// Writes a character to the terminal and shifts the cursor.
    fn put_char(&mut self, char: char) {
        // Create empty lines until we reach the current line.
        while self.view_y >= self.view.len() {
            self.view.push(self.line_supplier.next_line());
        }

        self.view[self.view_y].put_char(char, self.view_x);
        self.view_x += 1;
    }

    /// Moves the cursor to the start of the line.
    fn carriage_return(&mut self) {
        self.view_x = 0;
    }

    /// Moves the cursor down one line.
    ///
    /// NOTE: Also does an implicit '\r'. This is the common behavior, but
    /// there's no standard that mandates it, and in fact on some systems it is
    /// configurable. For instance, see the "LF" section of
    /// <https://vt100.net/annarbor/aaa-ug/appendixa.html>
    fn line_feed(&mut self) {
        self.view_x = 0;
        self.view_y += 1;

        if self.view_y >= self.height {
            self.scroll_down();
        }
    }

    /// Shifts the terminal by one line.
    fn scroll_down(&mut self) {
        if !self.view.is_empty() {
            self.view.remove(0);
        }

        // Callers (line_feed / cursor_down) only invoke scroll_down right
        // after incrementing view_y, so view_y >= 1 here.
        self.view_y -= 1;
    }

    /// Shifts the cursor up by one line.
    fn cursor_up(&mut self) {
        if self.view_y > 0 {
            self.view_y -= 1;
        }
    }

    /// Shifts the cursor down by one line.
    fn cursor_down(&mut self) {
        self.view_y += 1;

        if self.view_y >= self.height {
            self.scroll_down();
        }
    }
}

// Transliteration of core/internal/terminalemulator/terminalemulator_test.go.
#[cfg(test)]
mod tests {
    use std::cell::RefCell;
    use std::rc::Rc;

    use pretty_assertions::assert_eq;

    use super::*;

    // PARITY: Go's TestLineSupplier keeps `Lines []*TestLine` and the
    // terminal mutates the same lines through the interface pointers; the
    // shared Rc<RefCell<LineContent>> handles replicate that aliasing.
    #[derive(Default)]
    struct TestLineSupplier {
        lines: Rc<RefCell<Vec<Rc<RefCell<LineContent>>>>>,
    }

    impl TestLineSupplier {
        fn lines_handle(&self) -> Rc<RefCell<Vec<Rc<RefCell<LineContent>>>>> {
            Rc::clone(&self.lines)
        }
    }

    impl LineSupplier for TestLineSupplier {
        fn next_line(&mut self) -> Box<dyn Line> {
            let line = Rc::new(RefCell::new(LineContent {
                max_length: 64,
                content: Vec::new(),
            }));

            self.lines.borrow_mut().push(Rc::clone(&line));

            Box::new(TestLine { line_content: line })
        }
    }

    struct TestLine {
        line_content: Rc<RefCell<LineContent>>,
    }

    impl Line for TestLine {
        fn put_char(&mut self, c: char, offset: usize) {
            let _ = self.line_content.borrow_mut().put_char(c, offset);
        }
    }

    fn content_at(lines: &Rc<RefCell<Vec<Rc<RefCell<LineContent>>>>>, i: usize) -> String {
        lines.borrow()[i].borrow().content_as_string()
    }

    #[test]
    fn test_crlf() {
        let supplier = TestLineSupplier::default();
        let lines = supplier.lines_handle();
        let mut term = Terminal::new(Box::new(supplier), 10);

        term.write("one\ntwo\rwh");

        assert_eq!(lines.borrow().len(), 2);
        assert_eq!(content_at(&lines, 0), "one");
        assert_eq!(content_at(&lines, 1), "who");
    }

    #[test]
    fn test_cursor_motion() {
        let supplier = TestLineSupplier::default();
        let lines = supplier.lines_handle();
        let mut term = Terminal::new(Box::new(supplier), 10);

        term.write("one\ntwo");
        term.write("\x1b[Arous\x1b[Btasks");

        assert_eq!(lines.borrow().len(), 2);
        assert_eq!(content_at(&lines, 0), "onerous");
        assert_eq!(content_at(&lines, 1), "two    tasks");
    }

    #[test]
    fn test_scroll_past_height() {
        let supplier = TestLineSupplier::default();
        let lines = supplier.lines_handle();
        let mut term = Terminal::new(Box::new(supplier), 2);
        term.write("one\n");
        term.write("two\n");
        term.write("three\r\x1b[B"); // \r\x1b[B is the same as \n
        term.write("four\r");

        // At this point, the terminal has two lines in view:
        //   "three"
        //   "four"
        // The cursor is at the start of the second line. The cursor should be
        // unable to move up above "three".
        term.write("\x1b[A\x1b[Amodified");

        assert_eq!(lines.borrow().len(), 4);
        assert_eq!(content_at(&lines, 0), "one");
        assert_eq!(content_at(&lines, 1), "two");
        assert_eq!(content_at(&lines, 2), "modified");
        assert_eq!(content_at(&lines, 3), "four");
    }

    #[test]
    fn test_unknown_escape_sequences() {
        let supplier = TestLineSupplier::default();
        let lines = supplier.lines_handle();
        let mut term = Terminal::new(Box::new(supplier), 10);

        term.write("\x1b?");
        term.write("\x1b[?");

        assert_eq!(content_at(&lines, 0), "\x1b?\x1b[?");
    }
}
