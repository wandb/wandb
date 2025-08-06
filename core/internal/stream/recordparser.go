package stream

import (
	"context"

	"github.com/Khan/genqlient/graphql"
	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RecordParserProviders binds RecordParserFactory.
var RecordParserProviders = wire.NewSet(
	wire.Struct(new(RecordParserFactory), "*"),
)

// RecordParser turns Records into Work.
//
// Records coming from the client via interprocess communication, or those
// read from a transaction log, pass through here first.
type RecordParser interface {
	// Parse returns the Work corresponding to a Record.
	Parse(record *spb.Record) runwork.Work
}

// RecordParserFactory constructs the real RecordParser.
type RecordParserFactory struct {
	BeforeRunEndCtx    context.Context
	FeatureProvider    *featurechecker.ServerFeaturesCache
	GraphqlClientOrNil graphql.Client
	Logger             *observability.CoreLogger
	Operations         *wboperation.WandbOperations
	Run                *StreamRun

	ClientID sharedmode.ClientID
	Settings *settings.Settings
}

// New returns a new RecordParser.
func (f *RecordParserFactory) New(
	tbHandler *tensorboard.TBHandler,
) *recordParser {
	return &recordParser{*f, tbHandler}
}

// recordParser is the real implementation of RecordParser.
type recordParser struct {
	RecordParserFactory // injected fields

	tbHandler *tensorboard.TBHandler
}

// Ensure recordParser implements RecordParser.
var _ RecordParser = &recordParser{}

// Parse implements RecordParser.Parse.
func (p *recordParser) Parse(record *spb.Record) runwork.Work {
	switch {
	case record.GetRun() != nil:
		return &runupserter.RunUpdateWork{
			Record: record,

			StreamRunUpserter: p.Run,

			Settings:           p.Settings,
			BeforeRunEndCtx:    p.BeforeRunEndCtx,
			Operations:         p.Operations,
			FeatureProvider:    p.FeatureProvider,
			GraphqlClientOrNil: p.GraphqlClientOrNil,
			Logger:             p.Logger,
			ClientID:           string(p.ClientID),
		}

	case record.GetTbrecord() != nil:
		return &tensorboard.TBWork{
			Record:    record,
			Logger:    p.Logger,
			TBHandler: p.tbHandler,
		}

	case record.GetExit() != nil:
		return NewRunExitWork(RunExitWorkParams{
			Record:    record,
			TBHandler: p.tbHandler,
		})

	default:
		// Legacy style for handling records where the code to process them
		// lives in handler.go and sender.go directly.
		return runwork.WorkFromRecord(record)
	}
}
