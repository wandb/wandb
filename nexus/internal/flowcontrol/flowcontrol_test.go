package flowcontrol

import (
	"testing"

	"github.com/golang/mock/gomock"
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
	ctrl := gomock.NewController(t)
	m := NewMockTestFlowcontrol(ctrl)

	settings := &service.Settings{
		XNetworkBuffer: &wrapperspb.Int32Value{Value: 32},
	}
	records := []*service.Record{
		makeRecord(0),
		makeRecord(10),
		makeRecord(32),
	}
	gomock.InOrder(
		m.EXPECT().SendRecord(nexustest.MatchRecord(records[0], nexustest.RecordCompare)),
		m.EXPECT().SendRecord(nexustest.MatchRecord(records[1], nexustest.RecordCompare)),
		m.EXPECT().SendRecord(nexustest.MatchRecord(records[2], nexustest.RecordCompare)),
		m.EXPECT().SendPause(),
	)
	// m.EXPECT().RecoverRecords(gomock.Eq(99), gomock.Eq(33))
	flowControl := NewFlowControl(settings, m.SendRecord, m.SendPause, m.RecoverRecords)

	for _, record := range records {
		flowControl.Flow(record)
	}
}
