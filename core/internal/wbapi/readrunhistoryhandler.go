package wbapi

import (
	"context"
	"fmt"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/getsentry/sentry-go"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/runhistoryreader"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHistoryAPIHandler handles api requests
// related to reading a run's history.
type RunHistoryAPIHandler struct {
	graphqlClient graphql.Client
	httpClient    *retryablehttp.Client

	// mu protects scanHistoryReaders and downloadOperations from
	// concurrent access by goroutines spawned in handleApi.
	// RWMutex allows concurrent map reads while serializing writes.
	mu sync.RWMutex

	// rustArrowOnce guards one-time initialization of rustArrowWrapper.
	rustArrowOnce sync.Once

	// rustArrowWrapper is the wrapper for the Rust Arrow library.
	// It is used to provide FFI functions to the Go code for reading parquet files.
	rustArrowWrapper *ffi.RustArrowWrapper

	// rustArrowInitializationErr records an error from initializing rustArrowWrapper.
	rustArrowInitializationErr error

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
	graphqlClient graphql.Client,
	httpClient *retryablehttp.Client,
) *RunHistoryAPIHandler {

	return &RunHistoryAPIHandler{
		graphqlClient:      graphqlClient,
		httpClient:         httpClient,
		currentRequestId:   atomic.Int32{},
		scanHistoryReaders: make(map[int32]*runhistoryreader.HistoryReader),
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
	f.rustArrowOnce.Do(func() {
		f.rustArrowWrapper, f.rustArrowInitializationErr = ffi.NewRustArrowWrapper()
	})
	if f.rustArrowInitializationErr != nil {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ApiErrorResponse{
				ApiErrorResponse: &spb.ApiErrorResponse{
					Message: fmt.Sprintf(
						"RustArrowWrapper initialization failed: %v",
						f.rustArrowInitializationErr,
					),
				},
			},
		}
	}

	localHub := sentry.CurrentHub().Clone()
	localHub.WithScope(func(scope *sentry.Scope) {
		scope.SetTags(map[string]string{
			"entity":  request.Entity,
			"project": request.Project,
			"runId":   request.RunId,
		})
		localHub.CaptureMessage("handleScanRunHistoryInit")
	})

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
		f.rustArrowWrapper,
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

	f.mu.Lock()
	f.scanHistoryReaders[requestId] = historyReader
	f.mu.Unlock()

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

	f.mu.RLock()
	historyReader, ok := f.scanHistoryReaders[requestId]
	f.mu.RUnlock()

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

	localHub := sentry.CurrentHub().Clone()
	localHub.WithScope(func(scope *sentry.Scope) {
		scope.SetTags(map[string]string{
			"entity":  historyReader.GetEntity(),
			"project": historyReader.GetProject(),
			"runId":   historyReader.GetRunId(),
		})
		localHub.CaptureMessage(
			fmt.Sprintf(
				"handleScanRunHistoryRead: getHistorySteps time: %dms",
				getHistoryStepsEnd.Sub(getHistoryStepsStart).Milliseconds(),
			),
		)
	})

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

	f.mu.Lock()
	historyReader, ok := f.scanHistoryReaders[requestId]
	if ok && historyReader != nil {
		delete(f.scanHistoryReaders, requestId)
	}
	f.mu.Unlock()

	if ok && historyReader != nil {
		historyReader.Release()
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

	f.mu.Lock()
	f.downloadOperations[requestId] = downloadOperation
	f.mu.Unlock()

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
	f.mu.Lock()
	downloadOperation, ok := f.downloadOperations[request.GetRequestId()]
	if ok {
		delete(f.downloadOperations, request.GetRequestId())
	}
	f.mu.Unlock()

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

	f.mu.RLock()
	downloadOperation, ok := f.downloadOperations[requestId]
	f.mu.RUnlock()

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
