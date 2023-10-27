package nexustest

import (
	"fmt"

	"github.com/golang/mock/gomock"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type RecordMatcher struct {
	expectedRecord *service.Record
	compareFunc    func(*service.Record, *service.Record) bool
}

func (m *RecordMatcher) Matches(x interface{}) bool {
	if record, ok := x.(*service.Record); ok {
		return m.compareFunc(m.expectedRecord, record)
	}
	return false
}

func (m *RecordMatcher) String() string {
	return fmt.Sprintf("%+v (*service.Record)", m.expectedRecord)
}

func MatchRecord(expectedRecord *service.Record, compareFunc func(*service.Record, *service.Record) bool) gomock.Matcher {
	return &RecordMatcher{expectedRecord: expectedRecord, compareFunc: compareFunc}
}

func RecordCompare(expected *service.Record, actual *service.Record) bool {
	return expected == actual
}
