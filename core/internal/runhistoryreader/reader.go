package runhistoryreader

import (
	"context"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path/filepath"

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
	partitions   []iterator.RowIterator

	// Stores the minimum step where live (not yet exported) data starts.
	// This is used to determine if we need to query the W&B backend for data.
	minLiveStep int64
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

	err := historyReader.initParquetFiles(ctx)
	if err != nil {
		return nil, err
	}

	partitions := make([]iterator.RowIterator, len(historyReader.parquetFiles))
	for i, parquetFile := range historyReader.parquetFiles {
		selectedRows := iterator.SelectRows(
			parquetFile,
			iterator.StepKey,
			0,
			float64(math.MaxInt64),
			true,
		)
		selectedColumns, err := iterator.SelectColumns(
			iterator.StepKey,
			historyReader.keys,
			parquetFile.ParquetReader().MetaData().Schema,
			len(historyReader.keys) == 0,
		)
		if err != nil {
			return nil, err
		}

		rowIterator, err := iterator.NewRowIterator(
			ctx,
			parquetFile,
			selectedRows,
			selectedColumns,
		)
		if err != nil {
			for _, partition := range partitions {
				partition.Release()
			}
			return nil, err
		}
		partitions[i] = rowIterator
	}
	historyReader.partitions = partitions

	return historyReader, nil
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
		selectAllColumns,
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

func (h *HistoryReader) getParquetHistory(
	ctx context.Context,
	minStep int64,
	maxStep int64,
	selectAllColumns bool,
) ([]iterator.KeyValueList, error) {
	results := []iterator.KeyValueList{}

	// Update the query range. For consecutive ranges, the iterator will continue
	// from the current position. For non-consecutive, it will reset.
	for _, partition := range h.partitions {
		parquetDataIterator, ok := partition.(*iterator.ParquetDataIterator)
		if !ok {
			return nil, fmt.Errorf("partition is not a ParquetDataIterator")
		}
		parquetDataIterator.UpdateQueryRange(
			float64(minStep),
			float64(maxStep),
			false,
		)
	}

	multiIterator := iterator.NewMultiIterator(h.partitions)
	defer multiIterator.Release()
	for {
		next, err := multiIterator.Next()
		if err != nil {
			if err != iterator.ErrRowExceedsMaxValue {
				return nil, err
			}
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
	err := os.MkdirAll(downloadDir, 0755)
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
func (h *HistoryReader) initParquetFiles(ctx context.Context) error {
	signedUrls, liveData, err := h.getRunHistoryFileUrlsWithLiveSteps(ctx)
	if err != nil {
		return err
	}

	h.minLiveStep, err = getMinLiveStep(liveData)
	if err != nil {
		return err
	}

	for i, url := range signedUrls {
		var parquetFile *pqarrow.FileReader

		dir := os.Getenv("WANDB_CACHE_DIR")
		if dir == "" {
			dir, _ = os.UserCacheDir()
			dir = filepath.Join(dir, "wandb", "runhistory")
		}
		if dir == "" {
			return fmt.Errorf("failed to get runhistory cache directory")
		}

		fileName := fmt.Sprintf("%s_%s_%s_%d.runhistory.parquet", h.entity, h.project, h.runId, i)
		parquetFilePath := filepath.Join(dir, fileName)

		if _, err := os.Stat(parquetFilePath); err == nil {
			parquetFile, err = parquet.LocalParquetFile(parquetFilePath, true)
			if err != nil {
				return err
			}
		} else if len(h.keys) == 0 {
			// When the user doesn't specify any keys,
			// It is faster to download the entire parquet file
			// and process it locally.
			err = h.downloadRunHistoryFile(url, dir, fileName)
			if err != nil {
				return err
			}

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

func (h *HistoryReader) getRowIteratorsFromFiles(
	ctx context.Context,
	minStep int64,
	maxStep int64,
	selectAllColumns bool,
) ([]iterator.RowIterator, error) {
	partitions := make([]iterator.RowIterator, 0, len(h.parquetFiles))
	for _, parquetFile := range h.parquetFiles {
		selectedRows := iterator.SelectRows(
			parquetFile,
			iterator.StepKey,
			float64(minStep),
			float64(maxStep),
			false,
		)
		selectedColumns, err := iterator.SelectColumns(
			iterator.StepKey,
			h.keys,
			parquetFile.ParquetReader().MetaData().Schema,
			selectAllColumns,
		)
		if err != nil {
			return nil, err
		}

		rowIterator, err := iterator.NewRowIterator(
			ctx,
			parquetFile,
			selectedRows,
			selectedColumns,
		)
		if err != nil {
			for _, partition := range partitions {
				partition.Release()
			}
			return nil, err
		}
		partitions = append(partitions, rowIterator)
	}

	return partitions, nil
}
