package wbapi

import (
	"context"
	"fmt"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHistoryAPIHandler handles api requests
// related to reading a run's history.
type RunHistoryAPIHandler struct {
	graphqlClient graphql.Client
	httpClient    *retryablehttp.Client
	sentryClient  *sentry_ext.Client

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

func NewRunHistoryAPIHandler(
	s *settings.Settings,
	sentryClient *sentry_ext.Client,
) *RunHistoryAPIHandler {
	logger := observability.NewNoOpLogger()
	baseURL := stream.BaseURLFromSettings(logger, s)
	credentialProvider := stream.CredentialsFromSettings(logger, s)
	graphqlClient := stream.NewGraphQLClient(
		baseURL,
		"", /*clientID*/
		credentialProvider,
		logger,
		&observability.Peeker{},
		s,
	)

	httpClient := retryablehttp.NewClient()
	httpClient.RetryMax = int(s.GetFileTransferMaxRetries())
	httpClient.RetryWaitMin = s.GetFileTransferRetryWaitMin()
	httpClient.RetryWaitMax = s.GetFileTransferRetryWaitMax()
	httpClient.HTTPClient.Timeout = s.GetFileTransferTimeout()

	return &RunHistoryAPIHandler{
		graphqlClient:      graphqlClient,
		httpClient:         httpClient,
		currentRequestId:   atomic.Int32{},
		scanHistoryReaders: make(map[int32]*runhistoryreader.HistoryReader),
		sentryClient:       sentryClient,
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
	case *spb.ReadRunHistoryRequest_DownloadRunHistory:
		return f.handleDownloadRunHistory(request.GetDownloadRunHistory())
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
	f.sentryClient.CaptureMessage(
		"handleScanRunHistoryInit",
		map[string]string{
			"entity":  request.Entity,
			"project": request.Project,
			"runId":   request.RunId,
		},
	)
	defer f.sentryClient.Flush(2)

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
		request.UseCache,
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

	getHistoryStepsStart := time.Now()
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
	getHistoryStepsEnd := time.Now()
	f.sentryClient.CaptureMessage(
		fmt.Sprintf(
			"handleScanRunHistoryRead: getHistorySteps time: %dms",
			getHistoryStepsEnd.Sub(getHistoryStepsStart).Milliseconds(),
		),
		map[string]string{
			"entity":  historyReader.GetEntity(),
			"project": historyReader.GetProject(),
			"runId":   historyReader.GetRunId(),
		},
	)
	defer f.sentryClient.Flush(2)

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
				Response: &spb.ReadRunHistoryResponse_RunHistory{
					RunHistory: &spb.RunHistoryResponse{
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
	historyReader, ok := f.scanHistoryReaders[requestId]
	if ok && historyReader != nil {
		historyReader.Release()
		delete(f.scanHistoryReaders, requestId)
	}

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

// handleDownloadRunHistory handles a request to download
// a run's history.
func (f *RunHistoryAPIHandler) handleDownloadRunHistory(
	request *spb.DownloadRunHistory,
) *spb.ApiResponse {
	signedUrls, liveData, err := parquet.GetSignedUrlsWithLiveSteps(
		context.Background(),
		f.graphqlClient,
		request.Entity,
		request.Project,
		request.RunId,
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

	containsLiveData := len(liveData) > 0
	if request.RequireCompleteHistory && containsLiveData {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: "Run contains data that has not been exported to parquet files yet.",
				},
			},
		}
	}

	fileNames := make([]string, 0, len(signedUrls))
	for i, url := range signedUrls {
		fileName := fmt.Sprintf(
			"%s_%s_%s_%d.runhistory.parquet",
			request.Entity,
			request.Project,
			request.RunId,
			i,
		)
		err = parquet.DownloadRunHistoryFile(
			http.DefaultClient,
			url,
			request.DownloadDir,
			fileName,
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
		fileNames = append(fileNames, fileName)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_DownloadRunHistoryResponse{
			DownloadRunHistoryResponse: &spb.DownloadRunHistoryResponse{
				FileNames:        fileNames,
				ContainsLiveData: containsLiveData,
			},
		},
	}
}
