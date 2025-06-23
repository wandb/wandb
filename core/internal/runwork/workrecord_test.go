package runwork_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestWorkDebugInfo_NonRequest(t *testing.T) {
	rec := &spb.Record{RecordType: &spb.Record_Stats{}}

	info := runwork.WorkFromRecord(rec).DebugInfo()

	assert.Equal(t,
		"WorkRecord(*service_go_proto.Record_Stats); Control(<nil>)",
		info)
}

func TestWorkDebugInfo_Request(t *testing.T) {
	rec := &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_PartialHistory{},
			},
		},
	}

	info := runwork.WorkFromRecord(rec).DebugInfo()

	assert.Equal(t,
		"WorkRecord(*service_go_proto.Request_PartialHistory); Control(<nil>)",
		info)
}

func TestWorkDebugInfo_Control(t *testing.T) {
	rec := &spb.Record{
		Control: &spb.Control{
			Local:        true,
			ConnectionId: "123",
		},
	}

	info := runwork.WorkFromRecord(rec).DebugInfo()

	assert.Regexp(t, `WorkRecord\(<nil>\); Control\(.*true.*\)`, info)
	assert.Regexp(t, `WorkRecord\(<nil>\); Control\(.*123.*\)`, info)
}
