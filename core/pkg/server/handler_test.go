package server_test

import (
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func makeHandler(
	inChan, fwdChan chan *spb.Record,
	outChan chan *spb.Result,
	commit string,
) *server.Handler {
	h := server.NewHandler(
		commit,
		server.HandlerParams{
			Logger:          observability.NewNoOpLogger(),
			Settings:        &spb.Settings{},
			FwdChan:         fwdChan,
			OutChan:         outChan,
			TerminalPrinter: observability.NewPrinter(),
			SkipSummary:     true,
		},
	)

	go h.Do(inChan)

	return h
}

type data struct {
	items    map[string]string
	step     int64
	flush    bool
	stepNil  bool
	flushNil bool
}

func makeFlushRecord() *spb.Record {
	record := &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_Defer{
					Defer: &spb.DeferRequest{
						State: spb.DeferRequest_FLUSH_PARTIAL_HISTORY,
					},
				},
			},
		},
	}
	return record
}

func makePartialHistoryRecord(d data) *spb.Record {
	items := []*spb.HistoryItem{}
	for k, v := range d.items {
		items = append(items, &spb.HistoryItem{
			NestedKey: strings.Split(k, "."),
			ValueJson: v,
		})
	}
	partialHistoryRequest := &spb.PartialHistoryRequest{
		Item: items,
	}
	if !d.stepNil {
		partialHistoryRequest.Step = &spb.HistoryStep{Num: d.step}
	}
	if !d.flushNil {
		partialHistoryRequest.Action = &spb.HistoryAction{Flush: d.flush}
	}
	record := &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_PartialHistory{
					PartialHistory: partialHistoryRequest,
				},
			},
		},
		Control: &spb.Control{
			MailboxSlot: "junk",
		},
	}
	return record
}

func makeHistoryRecord(d data) *spb.Record {
	items := []*spb.HistoryItem{}
	for k, v := range d.items {
		items = append(items, &spb.HistoryItem{
			NestedKey: strings.Split(k, "."),
			ValueJson: v,
		})
	}
	history := &spb.HistoryRecord{
		Item: items,
		Step: &spb.HistoryStep{Num: d.step},
	}
	record := &spb.Record{
		RecordType: &spb.Record_History{
			History: history,
		},
		Control: &spb.Control{
			MailboxSlot: "junk",
		},
	}
	return record
}

func makeOutput(record *spb.Record) data {
	switch x := record.GetRecordType().(type) {
	case *spb.Record_History:
		history := x.History
		if history == nil {
			return data{}
		}
		items := map[string]string{}
		for _, item := range history.Item {
			// if strings.HasPrefix(item.Key, "_") {
			// 	continue
			// }
			items[strings.Join(item.NestedKey, ".")] = item.ValueJson
		}
		return data{
			items: items,
			step:  history.Step.Num,
		}
	case *spb.Record_Request:
		state := x.Request.GetDefer().GetState()
		if state != spb.DeferRequest_FLUSH_PARTIAL_HISTORY {
			return data{}
		}
		return data{
			flush: true,
		}
	default:
		return data{}
	}
}

type testCase struct {
	name     string
	input    []data
	expected []data
}

func TestHandlePartialHistory(t *testing.T) {
	testCases := []testCase{
		{
			name: "NoFlushIncreaseStepFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: false,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  1,
					flush: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NoFlushNoIncreaseStepFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: false,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  0,
					flush: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "3",
					},
					step: 0,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "FlushIncreaseStepFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: true,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  1,
					flush: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "FlushNoIncreaseStepFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: true,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  0,
					flush: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "FlushIncreaseStepNoFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: true,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  1,
					flush: false,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "FlushNoIncreaseStepNoFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: true,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  0,
					flush: false,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NoFlushIncreaseStepNoFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: false,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  1,
					flush: false,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NoFlushNoIncreaseStepNoFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step:  0,
					flush: false,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step:  0,
					flush: false,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "3",
					},
					step: 0,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NilStepNilFlushNilStepNilFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					stepNil:  true,
					flushNil: true,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					stepNil:  true,
					flushNil: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NilStepNilFlushNilStepNoFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					stepNil:  true,
					flushNil: true,
				},
				{
					items: map[string]string{
						"key1": "2",
						"key2": "3",
					},
					stepNil: true,
					flush:   false,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key1": "2",
						"key2": "3",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NilStepNilFlushNilStepFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					stepNil:  true,
					flushNil: true,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					stepNil: true,
					flush:   true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "StepNoFlushNilStepNilFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					step:  1,
					flush: false,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					stepNil:  true,
					flushNil: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "2",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "StepFlushNilStepNilFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					step:  1,
					flush: true,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					stepNil:  true,
					flushNil: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					step: 1,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					step: 2,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "StepNilFlushNilStepNilFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					step:     1,
					flushNil: true,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					stepNil:  true,
					flushNil: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "2",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NilStepFlushNilStepNilFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					stepNil: true,
					flush:   true,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					stepNil:  true,
					flushNil: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		{
			name: "NilStepNoFlushNilStepNilFlush",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
					},
					stepNil: true,
					flush:   false,
				},
				{
					items: map[string]string{
						"key1": "2",
					},
					stepNil:  true,
					flushNil: true,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1": "2",
					},
					step: 0,
				},
				{
					flush: true,
				},
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			inChan := make(chan *spb.Record, server.BufferSize)
			fwdChan := make(chan *spb.Record, server.BufferSize)
			outChan := make(chan *spb.Result, server.BufferSize)

			makeHandler(inChan, fwdChan, outChan, "" /*commit*/)

			for _, d := range tc.input {
				record := makePartialHistoryRecord(d)
				inChan <- record
			}

			inChan <- makeFlushRecord()

			for i, d := range tc.expected {
				record := <-fwdChan
				actual := makeOutput(record)
				assert.Equal(t, d.step, actual.step, "wrong step in record %d", i)
				for k, v := range d.items {
					assert.Equal(t, v, actual.items[k], "key=%s", k)
				}
				assert.Equal(t, d.flush, actual.flush, "wrong value of flush in record %d", i)
			}
		},
		)
	}
}

func TestHandleHistory(t *testing.T) {
	testCases := []testCase{
		{
			name: "IncreaseStep",
			input: []data{
				{
					items: map[string]string{
						"key1": "1",
						"key2": "2",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key2": "3",
					},
					step: 1,
				},
			},
			expected: []data{
				{
					items: map[string]string{
						"key1":     "1",
						"key2":     "2",
						"_step":    "0",
						"_runtime": "0.000000",
					},
					step: 0,
				},
				{
					items: map[string]string{
						"key2":     "3",
						"_step":    "1",
						"_runtime": "0.000000",
					},
					step: 1,
				},
				{
					flush: true,
				},
			},
		},
		// { // TODO: mock out time
		// 	name: "Timestamp",
		// 	input: []data{
		// 		{
		// 			items: map[string]string{
		// 				"key1":       "1",
		// 				"key2":       "2",
		// 				"_timestamp": "1.257894e+09",
		// 			},
		// 			step: 0,
		// 		},
		// 	},
		// 	expected: []data{
		// 		{
		// 			items: map[string]string{
		// 				"key1":     "1",
		// 				"key2":     "2",
		// 				"_runtime": "63393490800.000000",
		// 				"_step":    "0",
		// 			},
		// 			step: 0,
		// 		},
		// 		{
		// 			flush: true,
		// 		},
		// 	},
		// },
	}
	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			inChan := make(chan *spb.Record, server.BufferSize)
			fwdChan := make(chan *spb.Record, server.BufferSize)
			outChan := make(chan *spb.Result, server.BufferSize)

			makeHandler(inChan, fwdChan, outChan, "" /*commit*/)

			for _, d := range tc.input {
				record := makeHistoryRecord(d)
				inChan <- record
			}

			inChan <- makeFlushRecord()

			for _, d := range tc.expected {
				record := <-fwdChan
				actual := makeOutput(record)
				if actual.step != d.step {
					t.Errorf("expected step %v, got %v", d.step, actual.step)
				}
				for k, v := range actual.items {
					if d.items[k] != v {
						t.Errorf("expected %v, got %v", v, actual.items[k])
					}
				}
				if d.flush != actual.flush {
					t.Errorf("expected %v, got %v", d.flush, d.flush)
				}
			}
		})
	}

}

func TestHandleHeader(t *testing.T) {
	inChan := make(chan *spb.Record, 1)
	fwdChan := make(chan *spb.Record, 1)
	outChan := make(chan *spb.Result, 1)

	sha := "2a7314df06ab73a741dcb7bc5ecb50cda150b077"

	makeHandler(inChan, fwdChan, outChan, sha)

	record := &spb.Record{
		RecordType: &spb.Record_Header{
			Header: &spb.HeaderRecord{},
		},
	}
	inChan <- record

	record = <-fwdChan

	versionInfo := fmt.Sprintf("%s+%s", version.Version, sha)
	assert.Equal(t, versionInfo, record.GetHeader().GetVersionInfo().GetProducer(), "wrong version info")
}
