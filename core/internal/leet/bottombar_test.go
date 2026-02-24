package leet_test

import (
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func expandBottomBar(t *testing.T, bb *leet.BottomBar, height int) {
	t.Helper()

	bb.SetExpandedHeight(height)
	bb.Toggle()

	// Complete the animation deterministically (no sleep).
	bb.Update(time.Now().Add(leet.AnimationDuration + time.Millisecond))

	require.True(t, bb.IsExpanded(), "bottom bar should be expanded")
	require.False(t, bb.IsAnimating(), "bottom bar animation should be complete")
	require.Equal(t, height, bb.Height(), "expanded bottom bar height should match")
}

func makeLogs(n int) []leet.KeyValuePair {
	logs := make([]leet.KeyValuePair, n)
	for i := range n {
		logs[i] = leet.KeyValuePair{
			Key:   fmt.Sprintf("t%02d", i+1),
			Value: fmt.Sprintf("log %02d", i+1),
		}
	}
	return logs
}

func TestBottomBar_AutoScrollFreezesWhenUserScrollsUp(t *testing.T) {
	bb := leet.NewBottomBar()
	expandBottomBar(t, bb, 5) // border + header + 3 content lines

	bb.SetConsoleLogs(makeLogs(10))
	out := stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[9-10 of 10]", "should auto-scroll to the end initially")

	// User scrolls off the last line -> autoScroll should turn off.
	bb.Up()

	// New logs arrive: view should NOT jump to show the new end.
	bb.SetConsoleLogs(makeLogs(11))
	out = stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[9-10 of 11]", "should not jump to end when autoScroll is disabled")

	// Explicit scroll-to-end should re-enable auto-scroll.
	bb.ScrollToEnd()
	out = stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[10-11 of 11]", "ScrollToEnd should jump back to the end")
}

func TestBottomBar_PageUpDown_WrapsAround(t *testing.T) {
	bb := leet.NewBottomBar()
	expandBottomBar(t, bb, 4) // border + header + 2 content lines

	bb.SetConsoleLogs(makeLogs(5))
	out := stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[5-5 of 5]", "should start at end when auto-scroll is on")

	// PageDown from the end should wrap to the top.
	bb.PageDown()
	out = stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[1-1 of 5]", "PageDown at end should wrap to start")

	// PageUp from the top should wrap back to the end.
	bb.PageUp()
	out = stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[5-5 of 5]", "PageUp at start should wrap to end")
}

func TestWrapText_PreservesNewlinesAndWraps(t *testing.T) {
	tests := []struct {
		name     string
		text     string
		maxWidth int
		want     []string
	}{
		{
			name:     "short single line",
			text:     "hello",
			maxWidth: 10,
			want:     []string{"hello"},
		},
		{
			name:     "wrap at boundary",
			text:     "abcdefghij",
			maxWidth: 5,
			want:     []string{"abcde", "fghij"},
		},
		{
			name:     "embedded newline",
			text:     "abc\ndef",
			maxWidth: 10,
			want:     []string{"abc", "def"},
		},
		{
			name:     "wrap plus newline",
			text:     "abcdefghij\nxy",
			maxWidth: 5,
			want:     []string{"abcde", "fghij", "xy"},
		},
		{
			name:     "empty string",
			text:     "",
			maxWidth: 10,
			want:     []string{""},
		},
		{
			name:     "zero width returns original",
			text:     "abc",
			maxWidth: 0,
			want:     []string{"abc"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := leet.WrapText(tt.text, tt.maxWidth)
			require.Equal(t, tt.want, got)
		})
	}
}

func TestWithEllipsis(t *testing.T) {
	tests := []struct {
		name     string
		line     string
		maxWidth int
		want     string
	}{
		{
			name:     "fits without truncation marker",
			line:     "hello world! this is long",
			maxWidth: 10,
			want:     "hello w...",
		},
		{
			name:     "exactly marker width",
			line:     "hello",
			maxWidth: 3,
			want:     "...",
		},
		{
			name:     "below marker width",
			line:     "hello",
			maxWidth: 2,
			want:     "..",
		},
		{
			name:     "empty line",
			line:     "",
			maxWidth: 10,
			want:     "...",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := leet.WithEllipsis(tt.line, tt.maxWidth)
			require.Equal(t, tt.want, got)
		})
	}
}

func TestBottomBar_Down_CyclesAndWraps(t *testing.T) {
	bb := leet.NewBottomBar()
	expandBottomBar(t, bb, 5) // border + header + 3 content lines

	bb.SetConsoleLogs(makeLogs(5))
	out := stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[4-5 of 5]", "initial view should auto-scroll to end")

	// Move Down from last entry should wrap to first.
	bb.Down()
	out = stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[1-2 of 5]", "Down from last should wrap to first entry")

	// Continue Down through entries.
	bb.Down()
	out = stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[1-2 of 5]", "second Down should stay on page")

	// Down until we reach the last entry again (auto-scroll re-enables).
	for range 3 {
		bb.Down()
	}
	out = stripANSI(bb.View(80, "", ""))
	require.Contains(t, out, "[4-5 of 5]", "reaching last entry should re-enable auto-scroll")
}

func TestBottomBar_Down_EmptyLogs(t *testing.T) {
	bb := leet.NewBottomBar()
	expandBottomBar(t, bb, 5)

	// Down on empty logs should be a no-op.
	bb.Down()
	out := bb.View(80, "", "")
	require.NotEmpty(t, out, "view should render (empty content area)")
}
