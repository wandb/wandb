package handler_test

import (
	"testing"

	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type data struct {
	items    map[string]string
	step     int64
	flush    bool
	stepNil  bool
	flushNil bool
}

func makeFlushRecord() *pb.Record {
	record := &pb.Record{
		RecordType: &pb.Record_Request{
			Request: &pb.Request{
				RequestType: &pb.Request_Defer{
					Defer: &pb.DeferRequest{
						State: pb.DeferRequest_FLUSH_PARTIAL_HISTORY,
					},
				},
			},
		},
	}
	return record
}

func makePartialHistoryRecord(d data) *pb.Record {
	items := []*pb.HistoryItem{}
	for k, v := range d.items {
		items = append(items, &pb.HistoryItem{
			Key:       k,
			ValueJson: v,
		})
	}
	partialHistoryRequest := &pb.PartialHistoryRequest{
		Item: items,
	}
	if !d.stepNil {
		partialHistoryRequest.Step = &pb.HistoryStep{Num: d.step}
	}
	if !d.flushNil {
		partialHistoryRequest.Action = &pb.HistoryAction{Flush: d.flush}
	}
	record := &pb.Record{
		RecordType: &pb.Record_Request{
			Request: &pb.Request{
				RequestType: &pb.Request_PartialHistory{
					PartialHistory: partialHistoryRequest,
				},
			},
		},
		Control: &pb.Control{
			MailboxSlot: "junk",
		},
	}
	return record
}

func makeHistoryRecord(d data) *pb.Record {
	items := []*pb.HistoryItem{}
	for k, v := range d.items {
		items = append(items, &pb.HistoryItem{
			Key:       k,
			ValueJson: v,
		})
	}
	history := &pb.HistoryRecord{
		Item: items,
		Step: &pb.HistoryStep{Num: d.step},
	}
	record := &pb.Record{
		RecordType: &pb.Record_History{
			History: history,
		},
		Control: &pb.Control{
			MailboxSlot: "junk",
		},
	}
	return record
}

func makeOutput(record *pb.Record) data {
	switch x := record.GetRecordType().(type) {
	case *pb.Record_History:
		history := x.History
		if history == nil {
			return data{}
		}
		items := map[string]string{}
		for _, item := range history.Item {
			// if strings.HasPrefix(item.Key, "_") {
			// 	continue
			// }
			items[item.Key] = item.ValueJson
		}
		return data{
			items: items,
			step:  history.Step.Num,
		}
	case *pb.Record_Request:
		state := x.Request.GetDefer().GetState()
		if state != pb.DeferRequest_FLUSH_PARTIAL_HISTORY {
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
			inChan, loopbackChan := makeInboundChannels()
			fwdChan, outChan := makeOutboundChannels()

			makeHandler(inChan, loopbackChan, fwdChan, outChan, false)

			for _, d := range tc.input {
				record := makePartialHistoryRecord(d)
				inChan <- record
			}

			inChan <- makeFlushRecord()

			for _, d := range tc.expected {
				record := <-fwdChan
				actual := makeOutput(record)
				if actual.step != d.step {
					t.Errorf("expected step %v, got %v", d.step, actual.step)
				}
				for k, v := range d.items {
					if actual.items[k] != v {
						t.Errorf("expected %v, got %v", v, actual.items[k])
					}
				}
				if d.flush != actual.flush {
					t.Errorf("expected %v, got %v", d.flush, d.flush)
				}
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
			inChan, loopbackChan := makeInboundChannels()
			fwdChan, outChan := makeOutboundChannels()

			makeHandler(inChan, loopbackChan, fwdChan, outChan, false)

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
