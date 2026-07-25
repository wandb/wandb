package leet

import (
	"fmt"
	"os"
	"sync"
	"sync/atomic"
)

// Determinism hooks for the differential test harness (leet/harness).
//
// The harness runs this Go implementation as the behavioral oracle for the
// Rust port and diffs rendered frames cell-by-cell. Frames must therefore be
// a pure function of (fixture, scenario events, terminal size). All hooks are
// inert unless WANDB_LEET_TEST=1:
//
//   - animations snap to their target instead of easing over wall-clock time;
//   - the terminal is never queried for its background color; the background
//     is forced dark (or light via WANDB_LEET_TEST_BG=light);
//   - the media pane never emits Kitty/cell-size capability queries and stays
//     on the glyph renderer;
//   - history chunking is bounded by record count only, not wall-clock time;
//   - if LEET_TEST_ACK_FILE names a FIFO (or file) path, an ack line is
//     written there after every Update ("u <seq> <msgType>") and View
//     ("v <seq>"), letting the harness step scenarios without sleeping.

// testModeEnabled reports whether determinism hooks are active.
var testModeEnabled = sync.OnceValue(func() bool {
	return os.Getenv("WANDB_LEET_TEST") == "1"
})

// testForcedLightBackground reports whether the forced background is light.
// Only meaningful in test mode; the default is a dark background.
var testForcedLightBackground = sync.OnceValue(func() bool {
	return os.Getenv("WANDB_LEET_TEST_BG") == "light"
})

var testAckState = sync.OnceValue(func() *ackState {
	if !testModeEnabled() {
		return nil
	}
	path := os.Getenv("LEET_TEST_ACK_FILE")
	if path == "" {
		return nil
	}
	// The harness pre-creates the path (a FIFO, with its read end already
	// open, so this does not block; a regular file also works).
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND, 0)
	if err != nil {
		return nil
	}
	return &ackState{f: f}
})

type ackState struct {
	f *os.File

	// seq orders Update acks; View acks carry the latest Update seq so the
	// harness knows a frame reflecting that update has been rendered.
	seq atomic.Int64

	// mu serializes writes: Update runs on the program goroutine but View
	// may be called from the renderer.
	mu sync.Mutex
}

// testAckUpdate reports a processed message to the harness, if enabled.
func testAckUpdate(msg any) {
	s := testAckState()
	if s == nil {
		return
	}
	seq := s.seq.Add(1)
	s.mu.Lock()
	defer s.mu.Unlock()
	fmt.Fprintf(s.f, "u %d %T\n", seq, msg)
}

// testAckView reports a completed render to the harness, if enabled.
func testAckView() {
	s := testAckState()
	if s == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	fmt.Fprintf(s.f, "v %d\n", s.seq.Load())
}
