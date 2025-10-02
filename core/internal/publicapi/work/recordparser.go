package work

import (
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type RecordParser struct {
	Logger   *observability.CoreLogger
	Settings *settings.Settings
}

func (p *RecordParser) Parse(record *spb.Record) ApiWork {
	switch record.GetRecordType().(type) {
	case *spb.Record_Request:
		return p.parseRequest(record)
	default:
		return nil
	}
}

func (p *RecordParser) parseRequest(record *spb.Record) ApiWork {
	// TODO: implement ApiWork for ApiRequests
	return nil
}
