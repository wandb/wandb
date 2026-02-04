package parquet

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
		step, ok := liveDataMap[iterator.StepKey]
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

func GetFileSize(
	fileUrl string,
	httpClient *retryablehttp.Client,
) (int64, error) {
	resp, err := httpClient.Head(fileUrl)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()

	return resp.ContentLength, nil
}

// RunHistoryDownloadOperation is a download operation
// for managing and tracking the download of a run's history file(s).
type RunHistoryDownloadOperation struct {
	mu sync.Mutex

	// entity is the entity that owns the run.
	entity string

	// project is the project that the run belongs to.
	project string

	// runId is the ID of the run.
	runId string

	// downloadDir is the directory to store the downloaded history files within.
	downloadDir string

	// httpClient is the HTTP client to use for the download.
	httpClient *retryablehttp.Client

	// signedUrls is the list of signed URLs for the files to download.
	signedUrls []string

	// operations is the operations tracking the download.
	operations *wboperation.WandbOperations

	// filesDownloaded is the list of files that have been downloaded successfully.
	filesDownloaded []string

	// filesErrored is the map of files that have raised an error during the download.
	filesErrored map[string]error
}

func NewRunHistoryDownloadOperation(
	ctx context.Context,
	httpClient *retryablehttp.Client,
	entity string,
	project string,
	runId string,
	downloadDir string,
	signedUrls []string,
) (*RunHistoryDownloadOperation, error) {

	numberOfFiles := len(signedUrls)

	downloadOperation := &RunHistoryDownloadOperation{
		mu:              sync.Mutex{},
		entity:          entity,
		project:         project,
		runId:           runId,
		downloadDir:     downloadDir,
		httpClient:      httpClient,
		signedUrls:      signedUrls,
		operations:      wboperation.NewOperations(),
		filesDownloaded: make([]string, 0, numberOfFiles),
		filesErrored:    make(map[string]error, numberOfFiles),
	}

	return downloadOperation, nil
}

func (d *RunHistoryDownloadOperation) createDownloadTasks(
	ctx context.Context,
	operation *wboperation.WandbOperation,
) ([]*filetransfer.DefaultDownloadTask, error) {
	tasks := make([]*filetransfer.DefaultDownloadTask, 0, len(d.signedUrls))
	totalBytes := int64(0)

	for i, url := range d.signedUrls {
		fileName := fmt.Sprintf(
			"%s_%s_%s_%d.runhistory.parquet",
			d.entity,
			d.project,
			d.runId,
			i,
		)
		filePath := filepath.Join(d.downloadDir, fileName)
		fileSize, err := GetFileSize(url, d.httpClient)
		if err != nil {
			return nil, err
		}

		totalBytes += fileSize

		fileOp := operation.Subtask(fileName)
		task := &filetransfer.DefaultDownloadTask{
			FileKind: filetransfer.RunFileKindMedia,
			Path:     filePath,
			Url:      url,
			Size:     fileSize,
		}
		task.Context = fileOp.Context(ctx)
		task.OnComplete = func() {
			d.mu.Lock()
			defer d.mu.Unlock()

			fileOp.Finish()

			if task.Err != nil {
				d.filesErrored[filePath] = task.Err
			} else {
				d.filesDownloaded = append(d.filesDownloaded, filePath)
			}
		}

		tasks = append(tasks, task)
	}

	return tasks, nil
}

// StartDownloads begins all the download tasks for the files.
func (d *RunHistoryDownloadOperation) StartDownloads() ([]string, map[string]error) {
	parentOperation := d.operations.New("Downloading run history")
	operationCtx := parentOperation.Context(context.Background())
	defer parentOperation.Finish()

	fileTransferStats := filetransfer.NewFileTransferStats()
	fileTransfers := filetransfer.NewFileTransfers(
		d.httpClient,
		observability.NewNoOpLogger(),
		fileTransferStats,
	)
	fileTransferManager := filetransfer.NewFileTransferManager(
		filetransfer.FileTransferManagerOptions{
			Logger:            observability.NewNoOpLogger(),
			FileTransfers:     fileTransfers,
			FileTransferStats: fileTransferStats,
		},
	)

	tasks, err := d.createDownloadTasks(operationCtx, parentOperation)
	if err != nil {
		return nil, map[string]error{
			"error": err,
		}
	}

	for _, task := range tasks {
		fileTransferManager.AddTask(task)
	}
	fileTransferManager.Close()

	return d.filesDownloaded, d.filesErrored
}

// GetDownloadStatus returns the current status of the download operation.
func (d *RunHistoryDownloadOperation) GetDownloadStatus() *spb.DownloadRunHistoryStatusResponse {
	d.mu.Lock()
	defer d.mu.Unlock()

	errors := make(map[string]string, len(d.filesErrored))
	for file, err := range d.filesErrored {
		errors[file] = err.Error()
	}

	// Create a copy of filesDownloaded to avoid data race
	downloadedFiles := make([]string, len(d.filesDownloaded))
	copy(downloadedFiles, d.filesDownloaded)

	return &spb.DownloadRunHistoryStatusResponse{
		OperationStats: d.operations.ToProto(),
	}
}
