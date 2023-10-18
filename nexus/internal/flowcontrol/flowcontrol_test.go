package flowcontrol

import (
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

//go:generate mockgen -package=flowcontrol -source=flowcontrol_test.go -destination flowcontrol_test_gen.go MockTestFlow

type TestFlow interface {
	SendRecord(record *service.Record)
	SendPause()
	RecoverRecords(startOffset int64, endOffset int64)
}

func TestFlowControl(t *testing.T) {
	ctrl := gomock.NewController(t)

	m := NewMockTestFlow(ctrl)

	/*
			m.EXPECT().
		      RecoverRecords(gomock.Eq(99), gomock.Eq(33))
	*/
	settings := &service.Settings{
		RunId:          &wrapperspb.StringValue{Value: "run1"},
		XNetworkBuffer: &wrapperspb.Int32Value{Value: 20},
	}
	record := &service.Record{
		RecordType: &service.Record_Run{
			Run: &service.RunRecord{
				Project: "testProject",
				Entity:  "testEntity",
			}},
		Control: &service.Control{
			MailboxSlot: "junk",
		},
	}

	m.EXPECT().SendRecord(record)
	m.EXPECT().SendRecord(record)
	m.EXPECT().SendRecord(record)
	// m.EXPECT().SendPause()
	flowControl := NewFlowControl(settings, m.SendRecord, m.SendPause, m.RecoverRecords)

	flowControl.Flow(record)
	flowControl.Flow(record)
	flowControl.Flow(record)
	// assert.Equal(t, 1, 2)
}
