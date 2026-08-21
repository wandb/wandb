package leet_test

import (
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func findKV(items []leet.KeyValuePair, valueSubstr string) (leet.KeyValuePair, int, bool) {
	for i, kv := range items {
		if strings.Contains(kv.Value, valueSubstr) {
			return kv, i, true
		}
	}
	return leet.KeyValuePair{}, -1, false
}

func TestRunConsoleLogs_AssemblesAcrossCallsAndPreservesTimestamps(t *testing.T) {
	cl := leet.NewRunConsoleLogs()

	// Use fixed UTC times for deterministic HH:MM:SS keys.
	ts1 := time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC)
	ts2 := ts1.Add(2 * time.Second)

	// First write starts the current line.
	cl.ProcessRaw("first", false, ts1)

	// Second write begins with a newline, forcing a new line created under ts2.
	cl.ProcessRaw("\nsecond", false, ts2)

	items := cl.Items()
	require.NotEmpty(t, items, "expected assembled log items")

	kv1, i1, ok := findKV(items, "first")
	require.True(t, ok, "expected to find first line")
	require.Equal(t,
		ts1.Format("15:04:05"),
		kv1.Key,
		"first line should keep its creation timestamp")

	kv2, i2, ok := findKV(items, "second")
	require.True(t, ok, "expected to find second line")
	require.Equal(t,
		ts2.Format("15:04:05"),
		kv2.Key,
		"second line should use the second record timestamp")

	require.Less(t, i1, i2, "expected log lines to preserve arrival order")
}

func TestRunConsoleLogs_StripsNonCursorANSI(t *testing.T) {
	cl := leet.NewRunConsoleLogs()
	ts := time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC)

	// SGR colors and erase-line must not leak into assembled content.
	cl.ProcessRaw("\x1b[31mred\x1b[0m plain\x1b[K\n", false, ts)
	// OSC (BEL-terminated) must be dropped entirely.
	cl.ProcessRaw("\x1b]0;window title\aafter osc\n", false, ts)

	items := cl.Items()
	require.Len(t, items, 2)
	require.Equal(t, "red plain", items[0].Value)
	require.Equal(t, "after osc", items[1].Value)
}

func TestRunConsoleLogs_StripsEscapeSplitAcrossRecords(t *testing.T) {
	cl := leet.NewRunConsoleLogs()
	ts := time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC)

	// An SGR sequence split between two raw records must still be dropped.
	cl.ProcessRaw("\x1b[3", false, ts)
	cl.ProcessRaw("1mred\x1b[0m", false, ts)

	items := cl.Items()
	require.Len(t, items, 1)
	require.Equal(t, "red", items[0].Value)
}

func TestRunConsoleLogs_KeepsCursorMovementSequences(t *testing.T) {
	cl := leet.NewRunConsoleLogs()
	ts := time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC)

	// tqdm-style progress: cursor-up plus carriage return overwrites
	// the previous line and must keep working through the ANSI filter.
	cl.ProcessRaw("progress 10%\nnext\x1b[A\rprogress 90%", false, ts)

	items := cl.Items()
	require.Len(t, items, 2)
	require.Equal(t, "progress 90%", items[0].Value)
	require.Equal(t, "next", items[1].Value)
}

func TestRunConsoleLogs_ColoredLineWrapsAtVisibleWidth(t *testing.T) {
	cl := leet.NewRunConsoleLogs()
	ts := time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC)

	cl.ProcessRaw("\x1b[35m"+strings.Repeat("x", 12)+"\x1b[0m\n", false, ts)

	items := cl.Items()
	require.Len(t, items, 1)
	require.NotContains(t, items[0].Value, "\x1b", "no dangling escapes")
	require.Equal(t,
		[]string{"xxxxx", "xxxxx", "xx"},
		leet.WrapText(items[0].Value, 5),
		"should wrap at the visible width")
}
