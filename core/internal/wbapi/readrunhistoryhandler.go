package wbapi

import (
	"context"
	"fmt"
	"log/slog"
	"os"
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

	// downloadOperations is a map of request ids to download operations.
	//
	// It allows tracking the status of downloads for run history files.
	downloadOperations map[int32]*parquet.RunHistoryDownloadOperation
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
	httpClient.Logger = observability.NewCoreLogger(
		slog.Default(),
		nil,
	)

	return &RunHistoryAPIHandler{
		graphqlClient:      graphqlClient,
		httpClient:         httpClient,
		currentRequestId:   atomic.Int32{},
		scanHistoryReaders: make(map[int32]*runhistoryreader.HistoryReader),
		sentryClient:       sentryClient,
		downloadOperations: make(map[int32]*parquet.RunHistoryDownloadOperation),
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
	case *spb.ReadRunHistoryRequest_DownloadRunHistoryInit:
		return f.handleDownloadRunHistoryInit(request.GetDownloadRunHistoryInit())
	case *spb.ReadRunHistoryRequest_DownloadRunHistory:
		return f.handleDownloadRunHistory(request.GetDownloadRunHistory())
	case *spb.ReadRunHistoryRequest_DownloadRunHistoryStatus:
		return f.handleDownloadRunHistoryStatus(request.GetDownloadRunHistoryStatus())
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
		f.httpClient,
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

func (f *RunHistoryAPIHandler) handleDownloadRunHistoryInit(
	request *spb.DownloadRunHistoryInit,
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
					Message:   "Run contains data that has not been exported to parquet files yet.",
					ErrorType: spb.ErrorType_INCOMPLETE_RUN_HISTORY_ERROR.Enum(),
				},
			},
		}
	}

	err = os.MkdirAll(request.DownloadDir, 0o755)
	if err != nil {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: err.Error(),
				},
			},
		}
	}
	downloadOperation, err := parquet.NewRunHistoryDownloadOperation(
		context.Background(),
		f.httpClient,
		request.Entity,
		request.Project,
		request.RunId,
		request.DownloadDir,
		signedUrls,
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

	requestId := f.currentRequestId.Add(1)
	f.downloadOperations[requestId] = downloadOperation

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadRunHistoryResponse{
			ReadRunHistoryResponse: &spb.ReadRunHistoryResponse{
				Response: &spb.ReadRunHistoryResponse_DownloadRunHistoryInit{
					DownloadRunHistoryInit: &spb.DownloadRunHistoryInitResponse{
						RequestId:        requestId,
						ContainsLiveData: containsLiveData,
					},
				},
			},
		},
	}
}

// handleDownloadRunHistory handles a request to download a run's history.
func (f *RunHistoryAPIHandler) handleDownloadRunHistory(
	request *spb.DownloadRunHistory,
) *spb.ApiResponse {
	downloadOperation, ok := f.downloadOperations[request.GetRequestId()]
	if !ok || downloadOperation == nil {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: "Download operation not found.",
				},
			},
		}
	}

	downloadedFiles, errors := downloadOperation.StartDownloads()
	errorsMap := make(map[string]string, len(errors))
	for file, err := range errors {
		errorsMap[file] = err.Error()
	}

	delete(f.downloadOperations, request.GetRequestId())
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadRunHistoryResponse{
			ReadRunHistoryResponse: &spb.ReadRunHistoryResponse{
				Response: &spb.ReadRunHistoryResponse_DownloadRunHistory{
					DownloadRunHistory: &spb.DownloadRunHistoryResponse{
						DownloadedFiles: downloadedFiles,
						Errors:          errorsMap,
					},
				},
			},
		},
	}
}

// handleDownloadRunHistoryStatus handles a request
// to get the status of a download operation.
func (f *RunHistoryAPIHandler) handleDownloadRunHistoryStatus(
	request *spb.DownloadRunHistoryStatus,
) *spb.ApiResponse {
	requestId := request.GetRequestId()

	downloadOperation, ok := f.downloadOperations[requestId]
	if !ok || downloadOperation == nil {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: "Download operation not found.",
				},
			},
		}
	}

	downloadStatus := downloadOperation.GetDownloadStatus()
	if downloadStatus.Completed {
		delete(f.downloadOperations, requestId)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadRunHistoryResponse{
			ReadRunHistoryResponse: &spb.ReadRunHistoryResponse{
				Response: &spb.ReadRunHistoryResponse_DownloadRunHistoryStatus{
					DownloadRunHistoryStatus: downloadStatus,
				},
			},
		},
	}
}
