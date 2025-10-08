package work

import (
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type ReadRunHistoryWorkFactory struct {
	Logger *observability.CoreLogger
}

func (f *ReadRunHistoryWorkFactory) New(
	record *spb.Record,
) ApiWork {
	request := record.GetApiRequest().GetReadRunHistory()
	entity := request.Entity
	project := request.Project
	runId := request.RunId

	return &ReadRunHistoryWork{
		logger:        f.Logger,
		record:        record,
		historyReader: runhistoryreader.New(entity, project, runId),
	}
}

type ReadRunHistoryWork struct {
	logger *observability.CoreLogger
	record *spb.Record

	historyReader *runhistoryreader.HistoryReader
}

var _ ApiWork = &ReadRunHistoryWork{}

func (w *ReadRunHistoryWork) Process(outChan chan<- *spb.Result) {
	w.logger.Info("read run history work: processing", "request", w.record)
	request := w.record.GetApiRequest().GetReadRunHistory()
	keys := request.Keys
	minStep := request.MinStep
	maxStep := request.MaxStep

	// TODO: return history steps
	_ = w.historyReader.GetHistorySteps(keys, minStep, maxStep)

	result := &spb.Result{
		ResultType: &spb.Result_Response{
			Response: &spb.Response{
				ResponseType: &spb.Response_ApiResponse{
					ApiResponse: &spb.ApiResponse{
						Response: &spb.ApiResponse_ReadRunHistory{
							ReadRunHistory: &spb.ReadRunHistoryApiResponse{
								HistoryRows: []*spb.HistoryRow{},
							},
						},
					},
				},
			},
		},
		Control: w.record.GetControl(),
		Uuid:    w.record.GetUuid(),
	}
	outChan <- result
}
