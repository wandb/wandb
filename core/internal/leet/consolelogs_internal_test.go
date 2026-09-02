package leet

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestRunConsoleLogs_CapsScrollback(t *testing.T) {
	const maxLines = 100
	cl := NewRunConsoleLogs(maxLines)
	ts := time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC)

	total := maxLines + 5
	var b strings.Builder
	for i := range total - 1 {
		fmt.Fprintf(&b, "line %d\n", i)
	}
	b.WriteString("tail")
	cl.ProcessRaw(b.String(), false, ts)

	items := cl.Items()
	require.Len(t, items, maxLines, "scrollback should be capped")
	require.Equal(t, "line 5", items[0].Value, "oldest lines evicted first")
	require.Equal(t, "tail", items[len(items)-1].Value)
	require.Equal(t, ts.Format(consoleTimestampFormat), items[0].Key,
		"timestamp keys survive eviction")

	// A carriage-return overwrite of the live line must update the
	// correct entry even though eviction shifted slice indices.
	cl.ProcessRaw("\rOVERWRITTEN", false, ts)
	items = cl.Items()
	require.Len(t, items, maxLines)
	require.Equal(t, "OVERWRITTEN", items[len(items)-1].Value)
}
