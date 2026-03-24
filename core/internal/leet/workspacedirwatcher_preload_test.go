package leet_test

import (
	"reflect"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestFindRunMsg(t *testing.T) {
	want := leet.RunMsg{ID: "run-123", DisplayName: "demo"}

	tests := []struct {
		name string
		msg  tea.Msg
		want leet.RunMsg
		ok   bool
	}{
		{
			name: "direct run message",
			msg:  want,
			want: want,
			ok:   true,
		},
		{
			name: "chunked batch",
			msg: leet.ChunkedBatchMsg{
				Msgs: []tea.Msg{leet.SummaryMsg{}, want},
			},
			want: want,
			ok:   true,
		},
		{
			name: "batched records",
			msg: leet.BatchedRecordsMsg{
				Msgs: []tea.Msg{leet.ConsoleLogMsg{}, want},
			},
			want: want,
			ok:   true,
		},
		{
			name: "run without id is ignored",
			msg: leet.ChunkedBatchMsg{
				Msgs: []tea.Msg{leet.RunMsg{DisplayName: "missing-id"}},
			},
			ok: false,
		},
		{
			name: "no run message",
			msg: leet.ChunkedBatchMsg{
				Msgs: []tea.Msg{leet.SummaryMsg{}, leet.ConsoleLogMsg{}},
			},
			ok: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			got, ok := leet.FindRunMsg(tt.msg)
			if ok != tt.ok {
				t.Fatalf("findRunMsg() ok = %v, want %v", ok, tt.ok)
			}
			if !tt.ok {
				return
			}

			if !reflect.DeepEqual(got, tt.want) {
				t.Fatalf("findRunMsg() = %#v, want %#v", got, tt.want)
			}
		})
	}
}
