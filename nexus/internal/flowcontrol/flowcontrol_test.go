package flowcontrol

import (
	"fmt"
	"strconv"
	"strings"
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/nexus/internal/nexustest"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

//go:generate mockgen -package=flowcontrol -source=flowcontrol_test.go -destination flowcontrol_test_gen.go TestFlowcontrol

type TestFlowcontrol interface {
	SendRecord(record *service.Record)
	SendPause()
	RecoverRecords(startOffset int64, endOffset int64)
}

func makeRecord(offset int64) *service.Record {
	record := &service.Record{
		RecordType: &service.Record_History{
			History: &service.HistoryRecord{},
		},
		Control: &service.Control{
			StartOffset: offset,
		},
	}
	return record
}

func TestFlowControl(t *testing.T) {
	cases := []struct {
		NetworkBuffer int32
		Records       []int64
		Expect        string
	}{
		// no flowcontrol
		{64, []int64{0, 16, 32}, "s0,s1,s2"},
		// pause
		{32, []int64{0, 16, 32}, "s0,s1,s2,p"},
		// pause and no final send
		{32, []int64{0, 16, 32, 40}, "s0,s1,s2,p"},
	}
	for _, tc := range cases {
		t.Run(fmt.Sprintf("%d+%+v", tc.NetworkBuffer, tc.Records), func(t *testing.T) {
			ctrl := gomock.NewController(t)
			m := NewMockTestFlowcontrol(ctrl)

			settings := &service.Settings{
				XNetworkBuffer: &wrapperspb.Int32Value{Value: tc.NetworkBuffer},
			}
			records := []*service.Record{}
			for _, recordOffset := range tc.Records {
				records = append(records, makeRecord(recordOffset))
			}

			var orders []*gomock.Call
			expectStrings := strings.Split(tc.Expect, ",")
			for _, expect := range expectStrings {
				var gocall *gomock.Call
				switch expect[0] {
				case 's':
					num, err := strconv.Atoi(expect[1:])
					assert.Equal(t, nil, err)
					gocall = m.EXPECT().SendRecord(nexustest.MatchRecord(records[num], nexustest.RecordCompare))
				case 'p':
					gocall = m.EXPECT().SendPause()
				case 'r':
					gocall = m.EXPECT().RecoverRecords(gomock.Eq(99), gomock.Eq(33))
				default:
					panic("unhandled")
				}
				orders = append(orders, gocall)
			}
			gomock.InOrder(orders...)

			flowControl := NewFlowControl(settings, m.SendRecord, m.SendPause, m.RecoverRecords)
			for _, record := range records {
				flowControl.Flow(record)
			}
		})
	}
}
