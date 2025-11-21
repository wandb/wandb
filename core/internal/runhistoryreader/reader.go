package runhistoryreader

import (
	"context"
	"fmt"
	"io"
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
	}

	err := historyReader.initParquetFiles(ctx)
	if err != nil {
		return nil, err
	}

	return historyReader, nil
}

// GetHistorySteps gets all history rows for the given keys
// that fall between minStep and maxStep.
// Returns a list of KVMapLists, where each item in the list is a history row.
func (h *HistoryReader) GetHistorySteps(
	ctx context.Context,
	minStep int64,
	maxStep int64,
) ([]iterator.KeyValueList, error) {
	partitions := make([]iterator.RowIterator, len(h.parquetFiles))
	for i, parquetFile := range h.parquetFiles {
		selectedRows := iterator.SelectRows(
			parquetFile,
			iterator.StepKey,
			float64(minStep),
			float64(maxStep),
			false,
		)
		selectAllColumns := len(h.keys) == 0
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
		partitions[i] = rowIterator
	}

	multiIterator := iterator.NewMultiIterator(partitions)
	defer multiIterator.Release()

	results := []iterator.KeyValueList{}
	for {
		next, err := multiIterator.Next()
		if err != nil {
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
func (h *HistoryReader) getRunHistoryFileUrls(
	ctx context.Context,
) ([]string, error) {
	response, err := gql.RunParquetHistory(
		ctx,
		h.graphqlClient,
		h.entity,
		h.project,
		h.runId,
		[]string{iterator.StepKey},
	)
	if err != nil {
		return nil, err
	}

	if response.GetProject() == nil || response.GetProject().GetRun() == nil {
		return nil, fmt.Errorf("no parquet history found for run %s", h.runId)
	}

	signedUrls := response.GetProject().GetRun().GetParquetHistory().ParquetUrls
	return signedUrls, nil
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
func (h *HistoryReader) initParquetFiles(ctx context.Context) error {
	signedUrls, err := h.getRunHistoryFileUrls(ctx)
	if err != nil {
		return err
	}

	for i, url := range signedUrls {
		var parquetFile *pqarrow.FileReader

		// When the user doesn't specify any keys,
		// It is faster to download the entire parquet file
		// and process it locally.
		if len(h.keys) == 0 {
			tmpDir := os.TempDir()
			fileName := fmt.Sprintf("run_history_%d.parquet", i)

			err := h.downloadRunHistoryFile(url, tmpDir, fileName)
			if err != nil {
				return err
			}

			parquetFilePath := filepath.Join(tmpDir, fileName)
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
