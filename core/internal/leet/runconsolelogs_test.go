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
