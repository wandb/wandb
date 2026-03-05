package leet_test

import (
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func expandConsoleLogsPane(t *testing.T, clp *leet.ConsoleLogsPane, height int) {
	t.Helper()

	clp.SetExpandedHeight(height)
	clp.Toggle()

	// Complete the animation deterministically (no sleep).
	clp.Update(time.Now().Add(leet.AnimationDuration + time.Millisecond))

	require.True(t, clp.IsExpanded(), "bottom bar should be expanded")
	require.False(t, clp.IsAnimating(), "bottom bar animation should be complete")
	require.Equal(t, height, clp.Height(), "expanded bottom bar height should match")
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

func TestConsoleLogsPane_AutoScrollFreezesWhenUserScrollsUp(t *testing.T) {
	clp := leet.NewConsoleLogsPane()
	expandConsoleLogsPane(t, clp, 5) // border + header + 3 content lines

	clp.SetConsoleLogs(makeLogs(10))
	out := stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[9-10 of 10]", "should auto-scroll to the end initially")

	// User scrolls off the last line -> autoScroll should turn off.
	clp.Up()

	// New logs arrive: view should NOT jump to show the new end.
	clp.SetConsoleLogs(makeLogs(11))
	out = stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[9-10 of 11]", "should not jump to end when autoScroll is disabled")

	// Explicit scroll-to-end should re-enable auto-scroll.
	clp.ScrollToEnd()
	out = stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[10-11 of 11]", "ScrollToEnd should jump back to the end")
}

func TestConsoleLogsPane_PageUpDown_WrapsAround(t *testing.T) {
	clp := leet.NewConsoleLogsPane()
	expandConsoleLogsPane(t, clp, 4) // border + header + 2 content lines

	clp.SetConsoleLogs(makeLogs(5))
	out := stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[5-5 of 5]", "should start at end when auto-scroll is on")

	// PageDown from the end should wrap to the top.
	clp.PageDown()
	out = stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[1-1 of 5]", "PageDown at end should wrap to start")

	// PageUp from the top should wrap back to the end.
	clp.PageUp()
	out = stripANSI(clp.View(80, "", ""))
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

func TestConsoleLogsPane_Down_CyclesAndWraps(t *testing.T) {
	clp := leet.NewConsoleLogsPane()
	expandConsoleLogsPane(t, clp, 5) // border + header + 3 content lines

	clp.SetConsoleLogs(makeLogs(5))
	out := stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[4-5 of 5]", "initial view should auto-scroll to end")

	// Move Down from last entry should wrap to first.
	clp.Down()
	out = stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[1-2 of 5]", "Down from last should wrap to first entry")

	// Continue Down through entries.
	clp.Down()
	out = stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[1-2 of 5]", "second Down should stay on page")

	// Down until we reach the last entry again (auto-scroll re-enables).
	for range 3 {
		clp.Down()
	}
	out = stripANSI(clp.View(80, "", ""))
	require.Contains(t, out, "[4-5 of 5]", "reaching last entry should re-enable auto-scroll")
}

func TestConsoleLogsPane_Down_EmptyLogs(t *testing.T) {
	clp := leet.NewConsoleLogsPane()
	expandConsoleLogsPane(t, clp, 5)

	// Down on empty logs should be a no-op.
	clp.Down()
	out := clp.View(80, "", "")
	require.NotEmpty(t, out, "view should render (empty content area)")
}

func TestConsoleLogsPane_TimestampAdaptsToAvailableWidth(t *testing.T) {
	tests := []struct {
		name        string
		width       int
		wantFull    bool
		wantMinutes bool
	}{
		{
			name:     "enough_space_shows_hhmmss",
			width:    80, // int(80*0.12)=9 -> enough room after padding for 8 chars
			wantFull: true,
		},
		{
			name:        "narrow_truncates_to_hhmm",
			width:       70, // int(70*0.12)=8 -> NOT enough after padding for 8 chars
			wantMinutes: true,
		},
		{
			name:  "very_narrow_hides_timestamp",
			width: 30, // int(30*0.12)=3 -> too small even for HH:MM
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			clp := leet.NewConsoleLogsPane()
			expandConsoleLogsPane(t, clp, 4) // minimum height: border + header + 1 content line

			clp.SetConsoleLogs([]leet.KeyValuePair{
				{Key: "10:11:12", Value: "hello"},
			})

			out := stripANSI(clp.View(tt.width, "", ""))
			require.Contains(t, out, "hello", "log content should still render")

			switch {
			case tt.wantFull:
				require.Contains(t, out, "10:11:12")
			case tt.wantMinutes:
				require.Contains(t, out, "10:11")
				require.NotContains(t, out, "10:11:12")
				require.NotContains(t, out, "...", "timestamps should not use ellipsis truncation")
				require.NotContains(t, out, "10:11:", "should not show partial seconds")
			default:
				require.NotContains(t, out, "10:11:12")
				require.NotContains(t, out, "10:11")
				require.NotContains(t, out, "...", "hidden timestamps should not use ellipsis")
			}
		})
	}
}
