package stream_test

import (
	"fmt"
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

// These tests define the transaction log format on disk. Older clients,
// `wandb sync`, and `wandb leet` read this format.
//
// In stream.go, the Handler sends records to the Writer before the Sender
// gets them. The Writer puts this data on disk.
//
// Before you edit an assertion, bump transactionlog.wandbStoreVersion and
// add a migration note. A change to an assertion is a format change on disk.
//
// The Handler should not assign steps if they are not provided. The Sender
// assigns them through HistoryStepTracker after the Writer runs.

// makeFormatTestHandler creates a Handler and a channel to send work to it.
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

// nextFlush reads handler output until it gets the next History record. It
// reports if any Summary record before that History record has a "_step" key.
// The Handler sends Summary records before the History record for each flush
// (see flushPartialHistory). Thus nextFlush reads one full flush.
func nextFlush(handler *stream.Handler) (history *spb.HistoryRecord, summaryHasStep bool) {
	for {
		record := (<-handler.OutChan()).WorkImpl.(runwork.WorkRecord).Record

		if summary := record.GetSummary(); summary != nil {
			if hasStepKey(summary) {
				summaryHasStep = true
			}
			continue
		}

		if h := record.GetHistory(); h != nil {
			return h, summaryHasStep
		}
	}
}

// stepKeyItem matches "_step" as a flat key or as NestedKey: ["_step"].
type stepKeyItem interface {
	GetKey() string
	GetNestedKey() []string
}

func itemHasStepKey(item stepKeyItem) bool {
	if item.GetKey() == "_step" {
		return true
	}
	nested := item.GetNestedKey()
	return len(nested) == 1 && nested[0] == "_step"
}

func hasStepKey(r any) bool {
	switch x := r.(type) {
	case *spb.HistoryRecord:
		for _, item := range x.GetItem() {
			if itemHasStepKey(item) {
				return true
			}
		}
	case *spb.SummaryRecord:
		for _, item := range x.GetUpdate() {
			if itemHasStepKey(item) {
				return true
			}
		}
	default:
		panic(fmt.Sprintf("unexpected record type: %T", x))
	}
	return false
}

type partialHistoryOpt func(*spb.PartialHistoryRequest)

func withUserHistoryStep(n int64) partialHistoryOpt {
	return func(req *spb.PartialHistoryRequest) {
		req.Step = &spb.HistoryStep{Num: n}
	}
}

func withFlush() partialHistoryOpt {
	return func(req *spb.PartialHistoryRequest) {
		req.Action = &spb.HistoryAction{Flush: true}
	}
}

func historyItem(key, value string) *spb.HistoryItem {
	return &spb.HistoryItem{NestedKey: []string{key}, ValueJson: value}
}

func sendPartialHistory(
	inChan chan<- runwork.Work,
	items []*spb.HistoryItem,
	opts ...partialHistoryOpt,
) {
	req := &spb.PartialHistoryRequest{Item: items}
	for _, opt := range opts {
		opt(req)
	}
	inChan <- runwork.NoRequest(runwork.WorkRecord{
		Record: &spb.Record{
			RecordType: &spb.Record_Request{
				Request: &spb.Request{
					RequestType: &spb.Request_PartialHistory{
						PartialHistory: req,
					},
				},
			},
			Control: &spb.Control{MailboxSlot: "junk"},
		},
	})
}

func sendFlush(inChan chan<- runwork.Work) {
	inChan <- runwork.NoRequest(runwork.WorkRecord{Record: makeFlushRecord()})
}

// An auto-step row from `run.log({...})` must not write record.Step, a
// "_step" item, or summary "_step" to disk.
func TestHandlerHistoryFormat_AutoStep(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, false /*shared*/)

	sendPartialHistory(inChan, []*spb.HistoryItem{historyItem("a", "1")})

	history, summaryHasStep := nextFlush(handler)

	assert.Nil(t, history.GetStep(), "record.Step must not be set")
	assert.False(t, hasStepKey(history), "should not have a _step item")
	assert.False(t, summaryHasStep, "should not have a summary _step")
}

// An explicit-step row from `run.log({...}, step=5)` writes record.Step to
// disk for the monotonicity check and step-boundary flushes. It must not
// write a "_step" item or summary "_step".
func TestHandlerHistoryFormat_ExplicitStep(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, false /*shared*/)

	sendPartialHistory(
		inChan,
		[]*spb.HistoryItem{historyItem("a", "1")},
		withUserHistoryStep(5),
	)
	sendFlush(inChan)

	history, summaryHasStep := nextFlush(handler)

	if assert.NotNil(t, history.GetStep(), "record.Step must be set") {
		assert.Equal(t, int64(5), history.GetStep().GetNum())
	}
	assert.False(t, hasStepKey(history), "should not have a _step item")
	assert.False(t, summaryHasStep, "should not have a summary _step")
}

// In shared mode, no client owns step numbering. A history row must not write
// record.Step, a "_step" item, or summary "_step" to disk.
func TestHandlerHistoryFormat_SharedMode(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, true /*shared*/)

	sendPartialHistory(inChan, []*spb.HistoryItem{historyItem("a", "1")})

	history, summaryHasStep := nextFlush(handler)

	assert.Nil(t, history.GetStep(), "record.Step must not be set")
	assert.False(t, hasStepKey(history), "should not have a _step item")
	assert.False(t, summaryHasStep, "should not have a summary _step")
}

// After an explicit-step flush, the next auto-step row must not write
// record.Step to disk. The sender assigns the next step.
func TestHandlerHistoryFormat_ExplicitThenAutoStep(t *testing.T) {
	handler, inChan := makeFormatTestHandler(t, false /*shared*/)

	// Row 1: explicit step 5, with flush.
	sendPartialHistory(
		inChan,
		[]*spb.HistoryItem{historyItem("a", "1")},
		withUserHistoryStep(5),
		withFlush(),
	)
	firstHistory, _ := nextFlush(handler)
	if assert.NotNil(t, firstHistory.GetStep()) {
		assert.Equal(t, int64(5), firstHistory.GetStep().GetNum())
	}

	// Row 2: auto step.
	sendPartialHistory(inChan, []*spb.HistoryItem{historyItem("b", "2")})
	secondHistory, secondSummaryHasStep := nextFlush(handler)

	assert.Nil(t, secondHistory.GetStep(),
		"auto row after explicit-step flush must not have a step")
	assert.False(t, hasStepKey(secondHistory), "should not have a _step item")
	assert.False(t, secondSummaryHasStep, "should not have a summary _step")
}
