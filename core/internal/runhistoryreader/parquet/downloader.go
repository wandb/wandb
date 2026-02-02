package parquet

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gql"
)

// GetSignedUrlsWithLiveSteps retrieves signed URLs for downloading a run's
// parquet history files.
// Additionally, it returns the step numbers for any history data not yet exported.
//
// The order of URLs is not guaranteed to be consistent across calls.
func GetSignedUrlsWithLiveSteps(
	ctx context.Context,
	graphqlClient graphql.Client,
	entity string,
	project string,
	runId string,
) (signedUrls []string, liveSteps []int64, err error) {
	response, err := gql.RunParquetHistory(
		ctx,
		graphqlClient,
		entity,
		project,
		runId,
		[]string{StepKey},
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
	httpClient api.RetryableClient,
	fileUrl string,
	filePath string,
) (err error) {
	file, err := os.Create(filePath)
	if err != nil {
		return err
	}
	defer func() {
		if closeErr := file.Close(); closeErr != nil && err == nil {
			err = closeErr
		}
	}()

	req, err := retryablehttp.NewRequestWithContext(ctx, http.MethodGet, fileUrl, nil)
	if err != nil {
		return err
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	_, err = io.Copy(file, resp.Body)
	return err
}

func extractStepValuesFromLiveData(liveData []any) ([]int64, error) {
	if liveData == nil {
		return nil, nil
	}
	stepValues := make([]int64, 0, len(liveData))

	for _, data := range liveData {
		liveDataMap, ok := data.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("expected LiveData to be map[string]any")
		}
		step, ok := liveDataMap[StepKey]
		if !ok {
			return nil, fmt.Errorf("expected LiveData to contain step key")
		}

		// Step values are returned as float64 values from the backend.
		// So we convert them to int64 values before returning.
		stepValue, ok := step.(float64)
		if !ok {
			return nil, fmt.Errorf("expected step to be float64")
		}
		stepValues = append(stepValues, int64(stepValue))
	}
	return stepValues, nil
}
