package server

import (
	"fmt"
	"strings"
	"testing"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type data struct {
	items map[string]string
	step  int64
	flush bool
}

func makeInputRecord(d data) *service.Record {
	items := []*service.HistoryItem{}
	for k, v := range d.items {
		items = append(items, &service.HistoryItem{
			Key:       k,
			ValueJson: v,
		})
	}
	partialHistoryRequest := &service.PartialHistoryRequest{
		Item:   items,
		Step:   &service.HistoryStep{Num: d.step},
		Action: &service.HistoryAction{Flush: d.flush},
	}
	record := &service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_PartialHistory{
					PartialHistory: partialHistoryRequest,
				},
			},
		},
		Control: &service.Control{
			MailboxSlot: "junk",
		},
	}
	return record
}

func makeOutput(record *service.Record) data {
	history := record.GetHistory()
	if history == nil {
		return data{}
	}
	items := map[string]string{}
	for _, item := range history.Item {
		if strings.HasPrefix(item.Key, "_") {
			continue
		}
		items[item.Key] = item.ValueJson
	}
	return data{
		items: items,
		step:  history.Step.Num,
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
			},
		},
		{
			name: "NoFlushNoStepIncreaseFlush",
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
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			inChan, senderLoopbackChan, streamLoopbackChan := makeInboundChannels()
			h := makeHandler(inChan, senderLoopbackChan, streamLoopbackChan, false)

			for _, d := range tc.input {
				record := makeInputRecord(d)
				inChan <- record
			}

			for _, d := range tc.expected {
				record := <-h.fwdChan
				fmt.Println(record)
				actual := makeOutput(record)
				if actual.step != d.step {
					t.Errorf("expected step %v, got %v", d.step, actual.step)
				}
				for k, v := range d.items {
					if actual.items[k] != v {
						t.Errorf("expected %v, got %v", v, actual.items[k])
					}
				}
			}
		})
	}
}
