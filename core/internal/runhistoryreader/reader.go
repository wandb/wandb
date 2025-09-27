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

// HistoryReader downloads and reads an exisiting run's logged metrics.
type HistoryReader struct {
	ctx           context.Context
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
) *HistoryReader {
	return &HistoryReader{
		ctx:           ctx,
		entity:        entity,
		graphqlClient: graphqlClient,
		httpClient:    httpClient,
		project:       project,
		runId:         runId,
		keys:          keys,
	}
}

// GetHistorySteps gets all history rows for the given keys
// that fall between minStep and maxStep.
// Returns a list of KVMapLists, where each item in the list is a history row.
func (h *HistoryReader) GetHistorySteps(
	minStep int64,
	maxStep int64,
) ([]iterator.KeyValueList, error) {
	if len(h.parquetFiles) == 0 {
		signedUrls, err := h.getRunHistoryFileUrls(h.keys)
		if err != nil {
			return nil, err
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
					return nil, err
				}

				parquetFilePath := filepath.Join(tmpDir, fileName)
				parquetFile, err = parquet.LocalParquetFile(parquetFilePath, true)
				if err != nil {
					return nil, err
				}
			} else {
				httpFileReader, err := remote.NewHttpFileReader(
					context.Background(),
					h.httpClient,
					url,
				)
				if err != nil {
					return nil, err
				}

				parquetFile, err = parquet.RemoteParquetFile(
					context.Background(),
					httpFileReader,
				)
				if err != nil {
					return nil, err
				}
			}

			h.parquetFiles = append(h.parquetFiles, parquetFile)
		}
	}

	partitions := make([]iterator.RowIterator, len(h.parquetFiles))
	for i, parquetFile := range h.parquetFiles {
		partitions[i] = iterator.NewRowIterator(
			context.Background(),
			parquetFile,
			h.keys,
			iterator.WithHistoryPageRange(iterator.HistoryPageParams{
				MinStep: minStep,
				MaxStep: maxStep,
			}),
		)
	}

	multiIterator := iterator.NewMultiIterator(partitions)
	defer multiIterator.Release()

	results := []iterator.KeyValueList{}
	next, err := multiIterator.Next()
	for ; next && err == nil; next, err = multiIterator.Next() {
		select {
		case <-h.ctx.Done():
			return nil, h.ctx.Err()
		default:
			results = append(results, multiIterator.Value())
		}
	}

	return results, nil
}

// getRunHistoryFileUrls gets URLs
// that can be used to download a run's history files.
//
// The order of the URLs returned is not guaranteed
// to be the same order as the order the run history partitions were created in.
func (h *HistoryReader) getRunHistoryFileUrls() ([]string, error) {
	response, err := gql.RunParquetHistory(
		context.Background(),
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
