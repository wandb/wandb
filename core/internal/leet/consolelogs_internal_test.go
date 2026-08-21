package leet

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// wrappedLineCount must agree exactly with WrapText: the greedy wrapper
// produces more rows than ceil(width/maxWidth) when wide runes straddle
// chunk boundaries, and any disagreement makes autoscroll hide the
// newest rows and the [X-Y of N] header lie.
func TestWrappedLineCount_MatchesWrapText(t *testing.T) {
	tests := []struct {
		text     string
		maxWidth int
	}{
		{"", 3},
		{"plain ascii text", 5},
		{"abcdefghij", 5},
		{"a漢b漢", 2},
		{"x🚀x🚀", 2},
		{"a漢a漢a漢a漢", 4},
		{"漢漢漢", 2},
		{"漢", 1}, // wider than the wrap width
		{"line\nwith 漢 newlines", 2},
		{"🚀🚀x🚀", 3},
		{"tab\tand\x00control", 4},
	}

	for _, tt := range tests {
		got := wrappedLineCount(tt.text, tt.maxWidth)
		want := len(WrapText(tt.text, tt.maxWidth))
		require.Equalf(t, want, got, "text=%q maxWidth=%d", tt.text, tt.maxWidth)
	}
}

func TestRunConsoleLogs_CapsScrollback(t *testing.T) {
	cl := NewRunConsoleLogs()
	ts := time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC)

	total := maxConsoleLines + 5
	var b strings.Builder
	for i := range total - 1 {
		fmt.Fprintf(&b, "line %d\n", i)
	}
	b.WriteString("tail")
	cl.ProcessRaw(b.String(), false, ts)

	items := cl.Items()
	require.Len(t, items, maxConsoleLines, "scrollback should be capped")
	require.Equal(t, "line 5", items[0].Value, "oldest lines evicted first")
	require.Equal(t, "tail", items[len(items)-1].Value)
	require.Equal(t, ts.Format(consoleTimestampFormat), items[0].Key,
		"timestamp keys survive eviction")

	// A carriage-return overwrite of the live line must update the
	// correct entry even though eviction shifted slice indices.
	cl.ProcessRaw("\rOVERWRITTEN", false, ts)
	items = cl.Items()
	require.Len(t, items, maxConsoleLines)
	require.Equal(t, "OVERWRITTEN", items[len(items)-1].Value)
}
