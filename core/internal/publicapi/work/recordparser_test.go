package work

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestRecordParser_InvalidRecord(t *testing.T) {
	parser := &RecordParser{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.New(),
	}

	work := parser.Parse(&spb.Record{})

	assert.Nil(t, work)
}

func TestRecordParser_InvalidRequest(t *testing.T) {
	parser := &RecordParser{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.New(),
	}

	work := parser.Parse(&spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: nil,
			},
		},
	})

	assert.Nil(t, work)
}
