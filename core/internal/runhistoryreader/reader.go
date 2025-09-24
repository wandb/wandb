package runhistoryreader

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
)

// HistoryReader downloads and reads an exisiting run's logged metrics.
type HistoryReader struct {
	entity        string
	graphqlClient graphql.Client
	httpClient    *http.Client
	project       string
	runId         string
}

// New returns a new HistoryReader.
func New(
	entity string,
	project string,
	runId string,
	graphqlClient graphql.Client,
	httpClient *http.Client,
) *HistoryReader {
	return &HistoryReader{
		entity:        entity,
		graphqlClient: graphqlClient,
		httpClient:    httpClient,
		project:       project,
		runId:         runId,
	}
}

// GetHistorySteps gets all history rows for the given keys
// that fall between minStep and maxStep.
func (h *HistoryReader) GetHistorySteps(
	keys []string,
	minStep int64,
	maxStep int64,
) error {
	// TODO: Implement
	return fmt.Errorf("not implemented")
}

// getRunHistoryFileUrls gets signed URLs for a run's history files.
// These URLs can be used to download the files, or read remotely.
func (h *HistoryReader) getRunHistoryFileUrls(keys []string) ([]string, error) {
	response, err := gql.RunParquetHistory(
		context.Background(),
		h.graphqlClient,
		h.entity,
		h.project,
		h.runId,
		keys,
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
