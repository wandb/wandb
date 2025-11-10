package wbapi

import (
	"context"
	"net/http"
	"sync/atomic"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHistoryAPIHandler handles api requests
// related to reading a run's history.
type RunHistoryAPIHandler struct {
	graphqlClient graphql.Client
	httpClient    *retryablehttp.Client

	// currentRequestId is the id of the last scan init request made.
	//
	// It is used to provide a unique id for each scan request
	// and track the associated history reader.
	currentRequestId atomic.Int32

	// scanHistoryReaders is a map of request ids to history readers.
	//
	// It allows us to reuse existing
	// history readers for subsequent scan requests.
	scanHistoryReaders map[int32]*runhistoryreader.HistoryReader
}

func NewRunHistoryAPIHandler(settings *settings.Settings) *RunHistoryAPIHandler {
	backend := stream.NewBackend(observability.NewNoOpLogger(), settings)
	graphqlClient := stream.NewGraphQLClient(
		backend,
		settings,
		&observability.Peeker{},
		"",
	)

	httpClient := retryablehttp.NewClient()
	httpClient.RetryMax = int(settings.GetFileTransferMaxRetries())
	httpClient.RetryWaitMin = settings.GetFileTransferRetryWaitMin()
	httpClient.RetryWaitMax = settings.GetFileTransferRetryWaitMax()
	httpClient.HTTPClient.Timeout = settings.GetFileTransferTimeout()

	return &RunHistoryAPIHandler{
		graphqlClient:      graphqlClient,
		httpClient:         httpClient,
		currentRequestId:   atomic.Int32{},
		scanHistoryReaders: make(map[int32]*runhistoryreader.HistoryReader),
	}
}

func (f *RunHistoryAPIHandler) HandleRequest(
	request *spb.ReadRunHistoryRequest,
) *spb.ApiResponse {
	switch request.Request.(type) {
	case *spb.ReadRunHistoryRequest_ScanRunHistoryInit:
		return f.handleScanRunHistoryInit(request.GetScanRunHistoryInit())
	case *spb.ReadRunHistoryRequest_ScanRunHistory:
		return f.handleScanRunHistoryRead(request.GetScanRunHistory())
	case *spb.ReadRunHistoryRequest_ScanRunHistoryCleanup:
		return f.handleScanRunHistoryCleanup(request.GetScanRunHistoryCleanup())
	}

	return nil
}

// handleScanRunHistoryInit handles a request to initialize
// a scan over a run's history.
//
// It creates a new history reader for the run,
// and caches it for subsequent scan requests.
// It returns an Id correlating subsequent scan requests
// with the history reader.
func (f *RunHistoryAPIHandler) handleScanRunHistoryInit(
	request *spb.ScanRunHistoryInit,
) *spb.ApiResponse {
	requestId := f.currentRequestId.Add(1)
	requestKeys := request.GetKeys()

	historyReader, err := runhistoryreader.New(
		context.Background(),
		request.Entity,
		request.Project,
		request.RunId,
		f.graphqlClient,
		http.DefaultClient,
		requestKeys,
	)
	if err != nil {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: err.Error(),
				},
			},
		}
	}

	f.scanHistoryReaders[requestId] = historyReader

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadRunHistoryResponse{
			ReadRunHistoryResponse: &spb.ReadRunHistoryResponse{
				Response: &spb.ReadRunHistoryResponse_ScanRunHistoryInit{
					ScanRunHistoryInit: &spb.ScanRunHistoryInitResponse{
						RequestId: requestId,
					},
				},
			},
		},
	}
}

// handleScanRunHistoryRead handles a request to scan
// over a portion of a run's history.
func (f *RunHistoryAPIHandler) handleScanRunHistoryRead(
	request *spb.ScanRunHistory,
) *spb.ApiResponse {
	requestId := request.GetRequestId()

	historyReader, ok := f.scanHistoryReaders[requestId]

	if !ok || historyReader == nil {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: "Run history scan not initialized.",
				},
			},
		}
	}

	minStep := request.MinStep
	maxStep := request.MaxStep

	historySteps, err := historyReader.GetHistorySteps(
		context.Background(),
		minStep,
		maxStep,
	)
	if err != nil {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: err.Error(),
				},
			},
		}
	}

	historyRows := make([]*spb.HistoryRow, 0, len(historySteps))
	for _, historyStep := range historySteps {
		historyItems := make([]*spb.ParquetHistoryItem, 0, len(historyStep))
		for _, historyItem := range historyStep {
			valueJson, err := simplejsonext.MarshalToString(historyItem.Value)
			if err != nil {
				return &spb.ApiResponse{
					Response: &spb.ApiResponse_ApiErrorResponse{
						ApiErrorResponse: &spb.ApiErrorResponse{
							Message: err.Error(),
						},
					},
				}
			}

			historyItems = append(historyItems, &spb.ParquetHistoryItem{
				Key:       historyItem.Key,
				ValueJson: valueJson,
			})
		}
		historyRows = append(historyRows, &spb.HistoryRow{
			HistoryItems: historyItems,
		})
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadRunHistoryResponse{
			ReadRunHistoryResponse: &spb.ReadRunHistoryResponse{
				Response: &spb.ReadRunHistoryResponse_RunHistoryResponse{
					RunHistoryResponse: &spb.RunHistoryResponse{
						HistoryRows: historyRows,
					},
				},
			},
		},
	}
}

// handleScanRunHistoryCleanup cleans up resources
// associated with a history scan.
func (f *RunHistoryAPIHandler) handleScanRunHistoryCleanup(
	request *spb.ScanRunHistoryCleanup,
) *spb.ApiResponse {
	requestId := request.GetRequestId()
	delete(f.scanHistoryReaders, requestId)

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadRunHistoryResponse{
			ReadRunHistoryResponse: &spb.ReadRunHistoryResponse{
				Response: &spb.ReadRunHistoryResponse_ScanRunHistoryCleanup{
					ScanRunHistoryCleanup: &spb.ScanRunHistoryCleanupResponse{},
				},
			},
		},
	}
}
