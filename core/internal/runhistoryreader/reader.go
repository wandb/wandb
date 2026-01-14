package runhistoryreader

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"slices"

	"github.com/Khan/genqlient/graphql"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/remote"
)

// HistoryReader downloads and reads an existing run's logged metrics.
type HistoryReader struct {
	entity        string
	graphqlClient graphql.Client
	httpClient    *http.Client
	project       string
	runId         string

	keys         []string
	parquetFiles []*pqarrow.FileReader
	partitions   []*iterator.ParquetDataIterator

	// Stores the minimum step where live (not yet exported) data starts.
	// This is used to determine if we need to query the W&B backend for data.
	minLiveStep int64

	filePaths []string
}

// New returns a new HistoryReader.
func New(
	ctx context.Context,
	entity string,
	project string,
	runId string,
	graphqlClient graphql.Client,
	httpClient *http.Client,
	keys []string,
	useCache bool,
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

	err := historyReader.initParquetFiles(ctx, useCache)
	if err != nil {
		return nil, err
	}

	partitions, err := historyReader.makeRowIteratorsFromFiles(ctx)
	if err != nil {
		return nil, err
	}
	historyReader.partitions = partitions

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
) ([]iterator.KeyValueList, error) {
	results := []iterator.KeyValueList{}
	selectAllColumns := len(h.keys) == 0

	parquetHistory, err := h.getParquetHistory(
		ctx,
		minStep,
		maxStep,
	)
	if err != nil {
		return nil, err
	}
	results = append(results, parquetHistory...)

	liveHistory, err := h.getLiveData(ctx, minStep, maxStep, selectAllColumns)
	if err != nil {
		return nil, err
	}
	results = append(results, liveHistory...)

	return results, nil
}

// Release calls the Release method on each partition's ParquetDataIterator.
func (h *HistoryReader) Release() {
	for _, partition := range h.partitions {
		partition.Release()
	}
}

func (h *HistoryReader) getParquetHistory(
	ctx context.Context,
	minStep int64,
	maxStep int64,
) (results []iterator.KeyValueList, err error) {
	defer func() {
		if err != nil {
			for _, partition := range h.partitions {
				partition.Release()
			}
		}
	}()

	results = []iterator.KeyValueList{}

	for _, partition := range h.partitions {
		err := partition.UpdateQueryRange(
			float64(minStep),
			float64(maxStep),
		)
		if err != nil {
			return nil, err
		}
	}

	multiIterator := iterator.NewMultiIterator(h.partitions)
	for {
		next, err := multiIterator.Next()
		if err != nil && !errors.Is(err, iterator.ErrRowExceedsMaxValue) {
			slog.Error("error getting next row", "error", err)
			return nil, err
		}
		if !next {
			return results, nil
		}

		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
			results = append(results, multiIterator.Value())
		}
	}
}

// getRunHistoryFileUrls gets URLs
// that can be used to download a run's history files.
//
// The order of the URLs returned is not guaranteed
// to be the same order as the order the run history partitions were created in.
func (h *HistoryReader) getRunHistoryFileUrlsWithLiveSteps(
	ctx context.Context,
) (signedUrls []string, liveData []any, err error) {
	response, err := gql.RunParquetHistory(
		ctx,
		h.graphqlClient,
		h.entity,
		h.project,
		h.runId,
		[]string{iterator.StepKey},
	)
	if err != nil {
		return nil, nil, err
	}

	if response.GetProject() == nil || response.GetProject().GetRun() == nil {
		return nil, nil, fmt.Errorf("no parquet history found for run %s", h.runId)
	}

	liveData = response.GetProject().GetRun().GetParquetHistory().LiveData
	signedUrls = response.GetProject().GetRun().GetParquetHistory().ParquetUrls
	return signedUrls, liveData, nil
}

func (h *HistoryReader) downloadRunHistoryFile(
	fileUrl string,
	downloadDir string,
	fileName string,
) error {
	err := os.MkdirAll(downloadDir, 0o755)
	if err != nil {
		return err
	}

	file, err := os.Create(filepath.Join(downloadDir, fileName))
	if err != nil {
		return err
	}
	defer file.Close()

	resp, err := h.httpClient.Get(fileUrl)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	_, err = io.Copy(file, resp.Body)
	if err != nil {
		return err
	}

	return nil
}

// initParquetFiles creates a parquet file reader
// for each of the run's history files.
//
// It should be called before calling GetHistorySteps.
func (h *HistoryReader) initParquetFiles(
	ctx context.Context,
	useCache bool,
) error {
	signedUrls, liveData, err := parquet.GetSignedUrlsWithLiveSteps(
		ctx,
		h.graphqlClient,
		h.entity,
		h.project,
		h.runId,
	)
	if err != nil {
		return err
	}

	if len(liveData) > 0 {
		h.minLiveStep = slices.Min(liveData)
	}

	dir, err := getUserRunHistoryCacheDir()
	if err != nil {
		return err
	}

	if _, err := os.Stat(dir); os.IsNotExist(err) {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return err
		}
	}

	for i, url := range signedUrls {
		var parquetFile *pqarrow.FileReader

		fileName := fmt.Sprintf("%s_%s_%s_%d.runhistory.parquet", h.entity, h.project, h.runId, i)
		parquetFilePath := filepath.Join(dir, fileName)

		if _, err := os.Stat(parquetFilePath); useCache && err == nil {
			h.filePaths = append(h.filePaths, parquetFilePath)
			parquetFile, err = parquet.LocalParquetFile(parquetFilePath, true)
			if err != nil {
				return err
			}
		} else if len(h.keys) == 0 {
			// When the user doesn't specify any keys,
			// It is faster to download the entire parquet file
			// and process it locally.
			err = parquet.DownloadRunHistoryFile(
				h.httpClient,
				url,
				dir,
				fileName,
			)
			if err != nil {
				return err
			}

			h.filePaths = append(h.filePaths, parquetFilePath)
			parquetFile, err = parquet.LocalParquetFile(parquetFilePath, true)
			if err != nil {
				return err
			}
		} else {
			httpFileReader, err := remote.NewHttpFileReader(
				ctx,
				h.httpClient,
				url,
			)
			if err != nil {
				return err
			}

			parquetFile, err = parquet.RemoteParquetFile(
				httpFileReader,
			)
			if err != nil {
				return err
			}
		}

		h.parquetFiles = append(h.parquetFiles, parquetFile)
	}

	return nil
}

func (h *HistoryReader) makeRowIteratorsFromFiles(
	ctx context.Context,
) (partitions []*iterator.ParquetDataIterator, err error) {
	defer func() {
		if err != nil {
			for _, partition := range partitions {
				partition.Release()
			}
		}
	}()

	partitions = make([]*iterator.ParquetDataIterator, 0, len(h.parquetFiles))
	for _, parquetFile := range h.parquetFiles {
		selectedRows := iterator.SelectRowsInRange(
			parquetFile,
			iterator.StepKey,
			0,
			float64(math.MaxInt64),
		)
		selectedColumns, err := iterator.SelectColumns(
			iterator.StepKey,
			h.keys,
			parquetFile.ParquetReader().MetaData().Schema,
			len(h.keys) == 0,
		)
		if err != nil {
			return nil, err
		}

		parquetDataIterator, err := iterator.NewRowIterator(
			ctx,
			parquetFile,
			selectedRows,
			selectedColumns,
		)
		if err != nil {
			return nil, err
		}

		if parquetDataIterator != nil {
			partitions = append(partitions, parquetDataIterator)
		}
	}
	return partitions, nil
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
