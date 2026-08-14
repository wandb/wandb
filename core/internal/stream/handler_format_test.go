package stream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// The transaction log is a persisted format read by older clients, by
// `wandb sync`, and by `wandb leet`. Everything asserted below is what the
// Handler forwards to the Writer *before* the Sender ever sees a record
// (see stream.go's Handler -> Writer -> Sender pipeline), so it is exactly
// what ends up on disk. Any change to this table is an on-disk format
// change: bump transactionlog.wandbStoreVersion and add a migration note
// before editing it.
func makeFormatTestHandler(t *testing.T, shared bool) (*stream.Handler, chan runwork.Work) {
	t.Helper()

	inChan := make(chan runwork.Work, stream.BufferSize)

	s := settings.From(&spb.Settings{
		XShared: &wrapperspb.BoolValue{Value: shared},
	})

	handlerFactory := stream.HandlerFactory{
		Logger:          observabilitytest.NewTestLogger(t),
		Settings:        s,
		TerminalPrinter: observability.NewPrinter(0),
	}
	h := handlerFactory.New(runworktest.New())

	go h.Do(inChan)
	t.Cleanup(func() {
		close(inChan)
		for range h.OutChan() {
		}
	})

	return h, inChan
}

// nextFlush drains handler output up to and including the next History
// record, reporting whether any Summary record seen along the way carried
// a "_step" key. The Handler always forwards a flush's Summary record(s)
// before its History record (see flushPartialHistory), so this captures
// one full flush.
func nextFlush(handler *stream.Handler) (history *spb.HistoryRecord, summaryHasStep bool) {
	for {
		record := (<-handler.OutChan()).WorkImpl.(runwork.WorkRecord).Record

		if summary := record.GetSummary(); summary != nil {
			for _, item := range summary.GetUpdate() {
				if item.GetKey() == "_step" ||
					(len(item.GetNestedKey()) == 1 && item.GetNestedKey()[0] == "_step") {
					summaryHasStep = true
				}
			}
			continue
		}

		if h := record.GetHistory(); h != nil {
			return h, summaryHasStep
		}
	}
}

func historyItemKeys(h *spb.HistoryRecord) (hasStepItem bool) {
	for _, item := range h.GetItem() {
		if item.GetKey() == "_step" ||
			(len(item.GetNestedKey()) == 1 && item.GetNestedKey()[0] == "_step") {
			return true
		}
	}
	return false
}

// TestHandlerHistoryFormat_AutoStep pins the common `run.log({...})` case:
// merge base (4f92599d0) wrote record.Step, a "_step" item, and summary
// "_step" -- all three. This branch writes none of the three; the step is
// assigned downstream by the Sender's HistoryStepTracker, after the
// transaction log has already been written.
func TestHandlerHistoryFormat_AutoStep(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, false /*shared*/)

	inChan <- runwork.NoRequest(runwork.WorkRecord{
		Record: &spb.Record{
			RecordType: &spb.Record_Request{
				Request: &spb.Request{
					RequestType: &spb.Request_PartialHistory{
						PartialHistory: &spb.PartialHistoryRequest{
							Item: []*spb.HistoryItem{
								{NestedKey: []string{"a"}, ValueJson: "1"},
							},
						},
					},
				},
			},
			Control: &spb.Control{MailboxSlot: "junk"},
		},
	})

	history, summaryHasStep := nextFlush(handler)

	assert.Nil(t, history.GetStep(), "record.Step must not be set")
	assert.False(t, historyItemKeys(history), "no _step item")
	assert.False(t, summaryHasStep, "no summary _step")
}

// TestHandlerHistoryFormat_ExplicitStep pins `run.log({...}, step=5)`: merge
// base wrote record.Step, a "_step" item, and summary "_step" -- all three.
// This branch still writes record.Step (needed to gate the monotonicity
// check and to flush at step boundaries), but the "_step" item and summary
// "_step" are gone -- both are added downstream by the Sender.
func TestHandlerHistoryFormat_ExplicitStep(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, false /*shared*/)

	inChan <- runwork.NoRequest(runwork.WorkRecord{
		Record: &spb.Record{
			RecordType: &spb.Record_Request{
				Request: &spb.Request{
					RequestType: &spb.Request_PartialHistory{
						PartialHistory: &spb.PartialHistoryRequest{
							Item: []*spb.HistoryItem{
								{NestedKey: []string{"a"}, ValueJson: "1"},
							},
							Step: &spb.HistoryStep{Num: 5},
						},
					},
				},
			},
			Control: &spb.Control{MailboxSlot: "junk"},
		},
	})
	inChan <- runwork.NoRequest(runwork.WorkRecord{
		Record: &spb.Record{
			RecordType: &spb.Record_Request{
				Request: &spb.Request{
					RequestType: &spb.Request_PartialHistory{
						PartialHistory: &spb.PartialHistoryRequest{
							Action: &spb.HistoryAction{Flush: true},
						},
					},
				},
			},
		},
	})

	history, summaryHasStep := nextFlush(handler)

	if assert.NotNil(t, history.GetStep(), "record.Step must be set") {
		assert.Equal(t, int64(5), history.GetStep().GetNum())
	}
	assert.False(t, historyItemKeys(history), "no _step item")
	// The Handler's own summary derivation never touches "_step" -- that is
	// exclusively the Sender's HistoryStepTracker's job, downstream of the
	// transaction-log writer. A "_step" key can therefore never reach disk
	// via the Summary record, for an explicit step any more than an auto one.
	assert.False(t, summaryHasStep, "no summary _step")
}

// TestHandlerHistoryFormat_SharedMode pins shared mode, which is untouched
// by the format change at either merge base or here: no client owns step
// numbering, so none of the three fields is ever written.
func TestHandlerHistoryFormat_SharedMode(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, true /*shared*/)

	inChan <- runwork.NoRequest(runwork.WorkRecord{
		Record: &spb.Record{
			RecordType: &spb.Record_Request{
				Request: &spb.Request{
					RequestType: &spb.Request_PartialHistory{
						PartialHistory: &spb.PartialHistoryRequest{
							Item: []*spb.HistoryItem{
								{NestedKey: []string{"a"}, ValueJson: "1"},
							},
						},
					},
				},
			},
			Control: &spb.Control{MailboxSlot: "junk"},
		},
	})

	history, summaryHasStep := nextFlush(handler)

	assert.Nil(t, history.GetStep(), "record.Step must not be set")
	assert.False(t, historyItemKeys(history), "no _step item")
	assert.False(t, summaryHasStep, "no summary _step")
}

// TestHandlerHistoryFormat_ExplicitThenAutoStep covers a genuine gap: no
// test anywhere -- in this PR or at merge base -- exercises the transition
// from an explicit-step row to an auto-step row in the same run.
// partialHistoryStepIsExplicit is mutable state reset inside
// flushPartialHistory and read from three call sites; this pins whatever it
// currently does, so a future change to the transition is a visible diff
// rather than a silent one.
//
// Current behavior: the row right after an explicit-step flush does not
// get record.Step set, even though the internal step counter continued
// past the explicit value. This may be surprising, but it is what the code
// does today.
func TestHandlerHistoryFormat_ExplicitThenAutoStep(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, false /*shared*/)

	// Row 1: explicit step=5, flushed explicitly.
	inChan <- runwork.NoRequest(runwork.WorkRecord{
		Record: &spb.Record{
			RecordType: &spb.Record_Request{
				Request: &spb.Request{
					RequestType: &spb.Request_PartialHistory{
						PartialHistory: &spb.PartialHistoryRequest{
							Item: []*spb.HistoryItem{
								{NestedKey: []string{"a"}, ValueJson: "1"},
							},
							Step:   &spb.HistoryStep{Num: 5},
							Action: &spb.HistoryAction{Flush: true},
						},
					},
				},
			},
			Control: &spb.Control{MailboxSlot: "junk"},
		},
	})
	firstHistory, _ := nextFlush(handler)
	if assert.NotNil(t, firstHistory.GetStep()) {
		assert.Equal(t, int64(5), firstHistory.GetStep().GetNum())
	}

	// Row 2: auto step, no explicit step or flush action.
	inChan <- runwork.NoRequest(runwork.WorkRecord{
		Record: &spb.Record{
			RecordType: &spb.Record_Request{
				Request: &spb.Request{
					RequestType: &spb.Request_PartialHistory{
						PartialHistory: &spb.PartialHistoryRequest{
							Item: []*spb.HistoryItem{
								{NestedKey: []string{"b"}, ValueJson: "2"},
							},
						},
					},
				},
			},
			Control: &spb.Control{MailboxSlot: "junk"},
		},
	})
	secondHistory, secondSummaryHasStep := nextFlush(handler)

	assert.Nil(t, secondHistory.GetStep(),
		"BEHAVIOR PIN: the auto row right after an explicit-step row does"+
			" not carry record.Step, even though the internal step counter"+
			" advanced past the explicit value")
	assert.False(t, historyItemKeys(secondHistory), "no _step item")
	assert.False(t, secondSummaryHasStep, "no summary _step")
}
