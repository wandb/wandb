package stream_test

import (
	"log/slog"
	"strconv"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TestHistoryStepTracker_OldFormatLogIsUnchangedAndSilent pins the merge-base
// behavior (commit 4f92599d0, Handler.flushPartialHistory) for every row shape
// an older client could have written. Replaying such a row through the new
// Sender-side HistoryStepTracker must assign the same step the old code would
// have assigned, and must do so silently: no Sentry event and no log at
// WARN or above, since the old code produced neither for these logs.
func TestHistoryStepTracker_OldFormatLogIsUnchangedAndSilent(t *testing.T) {
	tests := []struct {
		name         string
		startingStep int64
		rows         []*spb.HistoryRecord
		wantSteps    []string
		shared       bool
	}{
		{
			// The common case: a non-shared history record wrote the step
			// twice, as HistoryRecord.Step and as a NestedKey:["_step"] item.
			name: "NestedKeyStepAndRecordStep",
			rows: []*spb.HistoryRecord{
				stepRow(0, []string{"_step"}, ""),
				stepRow(1, []string{"_step"}, ""),
				stepRow(2, []string{"_step"}, ""),
			},
			wantSteps: []string{"0", "1", "2"},
		},
		{
			// Pre-Go-core Python senders wrote "_step" as a flat key rather
			// than a single-element nested key.
			name: "FlatKeyStep",
			rows: []*spb.HistoryRecord{
				flatStepRow(0),
				flatStepRow(1),
				flatStepRow(2),
			},
			wantSteps: []string{"0", "1", "2"},
		},
		{
			// Some rows carried HistoryRecord.Step with no "_step" item at
			// all; the tracker must materialize the item.
			name: "RecordStepOnly",
			rows: []*spb.HistoryRecord{
				{Step: &spb.HistoryStep{Num: 0}},
				{Step: &spb.HistoryStep{Num: 1}},
				{Step: &spb.HistoryStep{Num: 2}},
			},
			wantSteps: []string{"0", "1", "2"},
		},
		{
			name: "SparseExplicitSteps",
			rows: []*spb.HistoryRecord{
				stepRow(0, []string{"_step"}, ""),
				stepRow(5, []string{"_step"}, ""),
				stepRow(10, []string{"_step"}, ""),
			},
			wantSteps: []string{"0", "5", "10"},
		},
		{
			// An offline-resumed run's own segment already carries steps
			// rebased onto the run's starting step; the tracker must not
			// renumber or warn about steps that are already monotonic.
			name:         "OnlineResumedRunAlreadyRebased",
			startingStep: 5,
			rows: []*spb.HistoryRecord{
				stepRow(5, []string{"_step"}, ""),
				stepRow(6, []string{"_step"}, ""),
				stepRow(7, []string{"_step"}, ""),
			},
			wantSteps: []string{"5", "6", "7"},
		},
		{
			// Shared-mode runs never carried a step axis and must remain
			// completely untouched.
			name:   "SharedMode",
			shared: true,
			rows: []*spb.HistoryRecord{
				{Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.5"}}},
				{Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.6"}}},
			},
			wantSteps: []string{"", ""},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			logger, logs, sentryTransport := observabilitytest.NewSentryTestLogger(t)
			x := makeHistoryStepTrackerWithLogger(
				t, logger, tt.shared, false /*serverSideDerivedSummary*/)

			for i, row := range tt.rows {
				wantItems := cloneHistoryItems(row.Item)
				wantStepSet := row.Step != nil

				x.Tracker.Process(row, tt.startingStep)

				if tt.shared {
					assert.Equal(t, wantItems, row.Item, "row %d", i)
					assert.Equal(t, wantStepSet, row.Step != nil, "row %d", i)
				}
				assert.Equal(t, tt.wantSteps[i], historyStepValue(row), "row %d", i)
			}

			if !tt.shared {
				assert.Equal(t,
					tt.wantSteps[len(tt.wantSteps)-1],
					summaryStepValue(t, x.RunSummary))
			}

			assert.Empty(t, sentryTransport.Events())
			observabilitytest.AssertNoLogsAtOrAbove(t, logs, slog.LevelWarn)
		})
	}
}

// TestHistoryStepTracker_OldLogRebasedOntoResume_WarnsAtMostOnce is the
// acceptance test for the R1 fix: renumbering an old log's steps onto a
// resumed run's starting step must log the fact once, not once per row.
//
// This fails on the current branch by design: ensureHistoryStep logs an
// un-rate-limited WARN on every renumbered row.
func TestHistoryStepTracker_OldLogRebasedOntoResume_WarnsAtMostOnce(t *testing.T) {
	logger, logs, sentryTransport := observabilitytest.NewSentryTestLogger(t)
	x := makeHistoryStepTrackerWithLogger(
		t, logger, false /*shared*/, false /*serverSideDerivedSummary*/)

	const numRows = 100
	const startingStep = int64(10)

	var lastRow *spb.HistoryRecord
	for i := int64(0); i < numRows; i++ {
		lastRow = stepRow(i, []string{"_step"}, "")
		x.Tracker.Process(lastRow, startingStep)
	}

	assert.Equal(t, strconv.FormatInt(startingStep+numRows-1, 10), historyStepValue(lastRow))
	assert.Equal(t, strconv.FormatInt(startingStep+numRows-1, 10), summaryStepValue(t, x.RunSummary))

	assert.LessOrEqual(t, len(sentryTransport.Events()), 1,
		"Sentry rate-limiting should cap events regardless of row count")
	warnRecords := observabilitytest.ExtractLogsAtOrAbove(t, logs, slog.LevelWarn)
	assert.LessOrEqual(t, len(warnRecords), 1,
		"renumbering %d rows should log a warning once, not once per row", numRows)
}

// TestHistoryStepTracker_UnparseableStepIsTolerated is the acceptance test
// for R3-Go: a history row with a non-integer "_step" value must not corrupt
// the row's step axis. It must not panic, must end up with exactly one
// "_step" item carrying an integer, and must warn about the bad value.
//
// This fails today for genuinely unparseable values: the tracker leaves the
// original, unparseable item in place and appends a second "_step" item from
// the auto-step counter.
func TestHistoryStepTracker_UnparseableStepIsTolerated(t *testing.T) {
	values := []string{
		`"5"`,
		"5.5",
		"null",
		"true",
		`{"a":1}`,
		"[1]",
		"-3",
		"9223372036854775808", // overflows int64
	}

	for _, value := range values {
		t.Run(value, func(t *testing.T) {
			logger, logs, _ := observabilitytest.NewSentryTestLogger(t)
			x := makeHistoryStepTrackerWithLogger(
				t, logger, false /*shared*/, false /*serverSideDerivedSummary*/)

			record := &spb.HistoryRecord{
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"loss"}, ValueJson: "0.5"},
					{NestedKey: []string{"_step"}, ValueJson: value},
				},
			}

			assert.NotPanics(t, func() {
				x.Tracker.Process(record, 0)
			})

			stepItems := 0
			for _, item := range record.Item {
				if len(item.GetNestedKey()) == 1 && item.GetNestedKey()[0] == "_step" {
					stepItems++
				}
			}
			assert.Equal(t, 1, stepItems, "expected exactly one _step item, got %d", stepItems)

			_, err := strconv.ParseInt(historyStepValue(record), 10, 64)
			assert.NoError(t, err, "resulting _step value must be an integer")
			assert.Equal(t, historyStepValue(record), summaryStepValue(t, x.RunSummary))

			warnRecords := observabilitytest.ExtractLogsAtOrAbove(t, logs, slog.LevelWarn)
			assert.Len(t, warnRecords, 1, "expected exactly one warning naming the bad value")
		})
	}
}

// TestHistoryStepTracker_EmitsRedundantSummaryUpdatePerRow pins R8: every
// processed row that materializes a step also streams a SummaryUpdate
// carrying "_step", except in the two cases where summary derivation is
// skipped entirely.
func TestHistoryStepTracker_EmitsRedundantSummaryUpdatePerRow(t *testing.T) {
	t.Run("NormalRow", func(t *testing.T) {
		x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)

		updates := x.Tracker.Process(&spb.HistoryRecord{
			Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.5"}},
		}, 0)

		assert.NotNil(t, updates)
	})

	t.Run("SharedMode", func(t *testing.T) {
		x := makeHistoryStepTracker(t, true /*shared*/, false /*serverSideDerivedSummary*/)

		updates := x.Tracker.Process(&spb.HistoryRecord{
			Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.5"}},
		}, 0)

		assert.Nil(t, updates)
	})

	t.Run("ServerSideDerivedSummary", func(t *testing.T) {
		x := makeHistoryStepTracker(t, false /*shared*/, true /*serverSideDerivedSummary*/)

		updates := x.Tracker.Process(&spb.HistoryRecord{
			Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.5"}},
		}, 0)

		assert.Nil(t, updates)
	})
}

// stepRow builds a history record whose step is written as an explicit
// nested-key item as well as HistoryRecord.Step, matching the merge-base
// (4f92599d0) Handler.flushPartialHistory output for a non-shared run.
func stepRow(step int64, nestedKey []string, loss string) *spb.HistoryRecord {
	return &spb.HistoryRecord{
		Step: &spb.HistoryStep{Num: step},
		Item: []*spb.HistoryItem{
			{NestedKey: nestedKey, ValueJson: strconv.FormatInt(step, 10)},
		},
	}
}

// flatStepRow builds a history record with a flat "_step" key, matching the
// pre-Go-core Python sender's output.
func flatStepRow(step int64) *spb.HistoryRecord {
	return &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{Key: "_step", ValueJson: strconv.FormatInt(step, 10)},
		},
	}
}

func cloneHistoryItems(items []*spb.HistoryItem) []*spb.HistoryItem {
	cloned := make([]*spb.HistoryItem, len(items))
	copy(cloned, items)
	return cloned
}
