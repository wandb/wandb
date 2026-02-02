package runhistoryreader

import (
	"context"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"slices"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
)

// HistoryReader downloads and reads an existing run's logged metrics.
type HistoryReader struct {
	// graphqlClient is the client to use to query the W&B backend.
	graphqlClient graphql.Client

	// httpClient is the client to use to download the history files.
	httpClient api.RetryableClient

	// entity is the entity to read history from.
	entity string

	// project is the project to read history from.
	project string

	// runId is the ID of the run to read history from.
	runId string

	// keys is the metrics to read from the history files.
	// If keys is empty, all metrics will be read.
	keys []string

	// Stores the minimum step where live (not yet exported) data starts.
	// This is used to determine if we need to query the W&B backend for data.
	minLiveStep int64

	// parquetReaders is the readers for the history files.
	parquetReaders []*ffi.RustArrowReader
}

// New returns a new HistoryReader.
func New(
	ctx context.Context,
	entity string,
	project string,
	runId string,
	graphqlClient graphql.Client,
	httpClient api.RetryableClient,
	keys []string,
	useCache bool,
	rustArrowWrapper *ffi.RustArrowWrapper,
) (*HistoryReader, error) {
	historyReader := &HistoryReader{
		entity:        entity,
		graphqlClient: graphqlClient,
		httpClient:    httpClient,
		project:       project,
		runId:         runId,
		keys:          keys,

		minLiveStep: math.MaxInt64,
	}

	filePaths, err := historyReader.getParquetFilePaths(ctx, useCache)
	if err != nil {
		return nil, err
	}

	for _, filePath := range filePaths {
		rustReader, err := ffi.CreateRustArrowReader(
			rustArrowWrapper,
			filePath,
			historyReader.keys,
		)
		if err != nil {
			return nil, err
		}
		historyReader.parquetReaders = append(historyReader.parquetReaders, rustReader)
	}
	return historyReader, nil
}

func (h *HistoryReader) GetEntity() string {
	return h.entity
}

func (h *HistoryReader) GetProject() string {
	return h.project
}

func (h *HistoryReader) GetRunId() string {
	return h.runId
}

// GetHistorySteps gets all history rows for HistoryReader's keys
// that fall between minStep and maxStep.
// Returns a list of KVMapLists, where each item in the list is a history row.
func (h *HistoryReader) GetHistorySteps(
	ctx context.Context,
	minStep int64,
	maxStep int64,
) ([]parquet.KeyValueList, error) {
	results := []parquet.KeyValueList{}
	for _, reader := range h.parquetReaders {
		resultsForPartition, err := reader.ScanStepRange(ctx, minStep, maxStep)
		if err != nil {
			return nil, err
		}
		results = append(results, resultsForPartition...)
	}

	selectAllColumns := len(h.keys) == 0
	livehistory, err := h.getLiveData(ctx, minStep, maxStep, selectAllColumns)
	if err != nil {
		return nil, err
	}
	results = append(results, livehistory...)

	return results, nil
}

// Release calls the Release method on each partition's ParquetDataIterator
// and frees any Rust resources.
func (h *HistoryReader) Release() {
	for _, reader := range h.parquetReaders {
		reader.Release()
	}
}

// getParquetFilePaths get the file paths for the run's history files.
// for each of the run's history files.
//
// It should be called before calling GetHistorySteps.
//
// Returns a list of file paths to the downloaded parquet files.
func (h *HistoryReader) getParquetFilePaths(
	ctx context.Context,
	useCache bool,
) ([]string, error) {
	signedUrls, liveData, err := parquet.GetSignedUrlsWithLiveSteps(
		ctx,
		h.graphqlClient,
		h.entity,
		h.project,
		h.runId,
	)
	if err != nil {
		return nil, err
	}

	if len(liveData) > 0 {
		h.minLiveStep = slices.Min(liveData)
	}

	dir, err := getUserRunHistoryCacheDir()
	if err != nil {
		return nil, err
	}

	filePaths := make([]string, 0, len(signedUrls))
	for i, url := range signedUrls {
		fileName := fmt.Sprintf("%s_%s_%s_%d.runhistory.parquet", h.entity, h.project, h.runId, i)
		parquetFilePath := filepath.Join(dir, fileName)

		if _, err := os.Stat(parquetFilePath); useCache && err == nil {
			filePaths = append(filePaths, parquetFilePath)
		} else if len(h.keys) == 0 {
			// When the user doesn't specify any keys,
			// It is faster to download the entire parquet file
			// and process it locally.
			err = parquet.DownloadRunHistoryFile(
				ctx,
				h.httpClient,
				url,
				parquetFilePath,
			)
			if err != nil {
				return nil, err
			}
			filePaths = append(filePaths, parquetFilePath)
		} else {
			filePaths = append(filePaths, url)
		}
	}

	return filePaths, nil
}

// getUserRunHistoryCacheDir returns the user's run history cache directory.
//
// returns the value of WANDB_CACHE_DIR environment variable if it is set.
// Otherwise it falls back to the OS provided cache directory.
func getUserRunHistoryCacheDir() (string, error) {
	dir := os.Getenv("WANDB_CACHE_DIR")
	if dir == "" {
		dir, _ = os.UserCacheDir()
		dir = filepath.Join(dir, "wandb", "runhistory")
	}
	if dir == "" {
		return "", fmt.Errorf("failed to get runhistory cache directory")
	}
	return dir, nil
}
