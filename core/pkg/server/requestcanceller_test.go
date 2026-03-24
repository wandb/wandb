package server_test

import (
	"bytes"
	"log/slog"
	"slices"
	"strings"
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/pkg/server"
)

// captureSlog redirects slog to a buffer for the duration of the test.
func captureSlog(t *testing.T) *bytes.Buffer {
	t.Helper()

	prev := slog.Default()
	t.Cleanup(func() { slog.SetDefault(prev) })

	var logs bytes.Buffer
	slog.SetDefault(slog.New(
		slog.NewTextHandler(&logs, &slog.HandlerOptions{}),
	))

	return &logs
}

func TestRequestCanceller_WarnsAtEachThreshold(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logs := captureSlog(t)

		rc := server.NewRequestCanceller()
		rc.SetWarnInterval(2)

		_, cancel1 := rc.Context("1")
		_, cancel2 := rc.Context("2") // warns with count=2
		cancel1()
		cancel2()
		synctest.Wait() // wait for cancellations to be applied

		_, cancel3 := rc.Context("new-1")
		_, cancel4 := rc.Context("new-2") // does not warn again for count=2
		_, cancel5 := rc.Context("new-3")
		_, cancel6 := rc.Context("new-4") // warns with count=4
		cancel3()
		cancel4()
		cancel5()
		cancel6()

		lines := slices.Collect(strings.Lines(logs.String()))
		require.Len(t, lines, 2)
		assert.Contains(t, lines[0], "many unfinished requests")
		assert.Contains(t, lines[0], "count=2")
		assert.Contains(t, lines[1], "many unfinished requests")
		assert.Contains(t, lines[1], "count=4")
	})
}
