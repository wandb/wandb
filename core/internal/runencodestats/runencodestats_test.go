package runencodestats_test

import (
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runencodestats"
)

func TestNilStats_IsNoOp(t *testing.T) {
	var stats *runencodestats.Stats

	// None of these may panic on a nil receiver. Components that are not
	// wired for telemetry, such as test fakes, rely on this.
	assert.NotPanics(t, func() {
		stats.AddHandlerParse(time.Second)
		stats.AddHandlerRecords(time.Second)
		stats.AddTxLogMarshal(time.Second)
		stats.AddSenderParse(time.Second)
		stats.AddHistoryRow(1, 2, time.Second)
		stats.AddSkippedOversizeRow()
		stats.AddRequest(1, 2, true, time.Second, time.Second)
		stats.AddHeartbeat()
	})

	assert.Nil(t, stats.Attributes())
}

func TestAttributes_NilWhenNothingHappened(t *testing.T) {
	stats := runencodestats.New()

	// Durations alone do not make a run worth reporting.
	stats.AddHandlerParse(time.Second)

	assert.Nil(t, stats.Attributes())
}

func TestAttributes_ReportsCounters(t *testing.T) {
	stats := runencodestats.New()

	stats.AddHistoryRow(3, 40, 5*time.Millisecond)
	stats.AddHistoryRow(2, 10, 1*time.Millisecond)
	stats.AddSkippedOversizeRow()
	stats.AddRequest(100, 30, true, 2*time.Millisecond, 3*time.Millisecond)
	stats.AddHeartbeat()
	stats.AddHandlerParse(7 * time.Millisecond)
	stats.AddHandlerRecords(8 * time.Millisecond)
	stats.AddTxLogMarshal(9 * time.Millisecond)
	stats.AddSenderParse(11 * time.Millisecond)

	attrs := stats.Attributes()
	require.NotNil(t, attrs)

	assert.Equal(t, "jsonl", attrs["format"])
	assert.Equal(t, "2", attrs["rows"])
	assert.Equal(t, "5", attrs["cells"])
	assert.Equal(t, "50", attrs["row_bytes"])
	assert.Equal(t, "1", attrs["skipped_oversize_rows"])
	assert.Equal(t, "1", attrs["requests"])
	assert.Equal(t, "1", attrs["heartbeats"])
	assert.Equal(t, "1", attrs["gzip_requests"])
	assert.Equal(t, "100", attrs["uncompressed_bytes"])
	assert.Equal(t, "30", attrs["compressed_bytes"])

	assert.Equal(t, ms(6), attrs["row_render_nanos"])
	assert.Equal(t, ms(2), attrs["envelope_nanos"])
	assert.Equal(t, ms(3), attrs["compress_nanos"])
	assert.Equal(t, ms(7), attrs["handler_parse_nanos"])
	assert.Equal(t, ms(8), attrs["handler_records_nanos"])
	assert.Equal(t, ms(9), attrs["txlog_marshal_nanos"])
	assert.Equal(t, ms(11), attrs["sender_parse_nanos"])
}

func TestAttributes_CarriesNoMetricNamesOrValues(t *testing.T) {
	stats := runencodestats.New()
	stats.AddHistoryRow(1, 2, time.Millisecond)

	// Every value must be a number, except the format label. This is the
	// privacy constraint from the design: counts and sizes only.
	for key, value := range stats.Attributes() {
		if key == "format" {
			continue
		}
		_, err := strconv.ParseInt(value, 10, 64)
		assert.NoErrorf(t, err, "attribute %q is not a number: %q", key, value)
	}
}

// TestConcurrentAccumulation covers the reason every field is atomic: the
// hops run in four different goroutines.
func TestConcurrentAccumulation(t *testing.T) {
	stats := runencodestats.New()

	const goroutines = 8
	const perGoroutine = 500

	var wg sync.WaitGroup
	for range goroutines {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for range perGoroutine {
				stats.AddHistoryRow(2, 3, time.Nanosecond)
				stats.AddRequest(5, 4, true, time.Nanosecond, time.Nanosecond)
				stats.AddHandlerParse(time.Nanosecond)
				stats.AddSenderParse(time.Nanosecond)
			}
		}()
	}
	wg.Wait()

	total := goroutines * perGoroutine
	attrs := stats.Attributes()
	require.NotNil(t, attrs)

	assert.Equal(t, itoa(total), attrs["rows"])
	assert.Equal(t, itoa(total*2), attrs["cells"])
	assert.Equal(t, itoa(total*3), attrs["row_bytes"])
	assert.Equal(t, itoa(total), attrs["requests"])
	assert.Equal(t, itoa(total*5), attrs["uncompressed_bytes"])
	assert.Equal(t, itoa(total*4), attrs["compressed_bytes"])
	assert.Equal(t, itoa(total), attrs["handler_parse_nanos"])
	assert.Equal(t, itoa(total), attrs["sender_parse_nanos"])
}

func ms(n int64) string {
	return strconv.FormatInt(int64(time.Duration(n)*time.Millisecond), 10)
}

func itoa(n int) string {
	return strconv.Itoa(n)
}
