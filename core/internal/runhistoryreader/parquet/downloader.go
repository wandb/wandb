package parquet

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
)

// GetSignedUrlsWithLiveSteps gets URLs
// that can be used to download a run's history files.
// As well as any steps which have not been exported to parquet files yet.
//
// The order of the URLs returned is not guaranteed
// to be the same order as the order the run history partitions were created in.
func GetSignedUrlsWithLiveSteps(
	ctx context.Context,
	graphqlClient graphql.Client,
	entity string,
	project string,
	runId string,
) (signedUrls []string, liveData []any, err error) {
	response, err := gql.RunParquetHistory(
		ctx,
		graphqlClient,
		entity,
		project,
		runId,
		[]string{iterator.StepKey},
	)
	if err != nil {
		return nil, nil, err
	}

	if response.GetProject() == nil || response.GetProject().GetRun() == nil {
		return nil, nil, fmt.Errorf("no parquet history found for run %s", runId)
	}

	signedUrls = response.GetProject().GetRun().GetParquetHistory().ParquetUrls
	liveData = response.GetProject().GetRun().GetParquetHistory().LiveData
	return signedUrls, liveData, nil
}

func DownloadRunHistoryFile(
	httpClient *http.Client,
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

	resp, err := httpClient.Get(fileUrl)
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
