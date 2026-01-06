package parquet

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
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
) (signedUrls []string, liveSteps []float64, err error) {
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

	liveDataResponse := response.GetProject().GetRun().GetParquetHistory().LiveData
	liveSteps, err = extractStepValuesFromLiveData(liveDataResponse)
	if err != nil {
		return nil, nil, err
	}

	signedUrls = response.GetProject().GetRun().GetParquetHistory().ParquetUrls
	return signedUrls, liveSteps, nil
}

// DownloadRunHistoryFile downloads a run history file from a given URL
// to the provided file path.
//
// The path where the file will be written to must already exist before
// calling this function.
func DownloadRunHistoryFile(
	ctx context.Context,
	httpClient *retryablehttp.Client,
	fileUrl string,
	filePath string,
) error {
	file, err := os.Create(filePath)
	if err != nil {
		return err
	}
	defer file.Close()

	req, err := retryablehttp.NewRequestWithContext(
		ctx,
		http.MethodGet,
		fileUrl,
		nil,
	)
	if err != nil {
		return err
	}
	resp, err := httpClient.Do(req)
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

func extractStepValuesFromLiveData(liveData []any) ([]float64, error) {
	stepValues := make([]float64, 0, len(liveData))
	if liveData == nil {
		return stepValues, nil
	}

	for _, data := range liveData {
		liveDataMap, ok := data.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("expected liveData to be map[string]any")
		}
		step, ok := liveDataMap[iterator.StepKey]
		if !ok {
			return nil, fmt.Errorf("expected liveData to contain step key")
		}
		stepValue, ok := step.(float64)
		if !ok {
			return nil, fmt.Errorf("expected step to be float64")
		}

		stepValues = append(stepValues, stepValue)
	}
	return stepValues, nil
}
