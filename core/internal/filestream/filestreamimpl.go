package filestream

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"

	"github.com/wandb/wandb/core/internal/api"
)

// startProcessingUpdates asynchronously ingests updates.
//
// This returns a channel of requests to send.
func (fs *fileStream) startProcessingUpdates(
	updates <-chan Update,
) <-chan *FileStreamRequest {
	requests := make(chan *FileStreamRequest)

	go func() {
		defer close(requests)

		fs.logger.Debug("filestream: open", "path", fs.path)

		for update := range updates {
			err := update.Apply(UpdateContext{
				MakeRequest: func(req *FileStreamRequest) {
					requests <- req
				},

				Settings: fs.settings,

				Logger:  fs.logger,
				Printer: fs.printer,
			})

			if err != nil {
				fs.logFatalAndStopWorking(err)
				break
			}
		}

		// Flush input channel if we exited early.
		for range updates {
		}
	}()

	return requests
}

// startTransmitting makes requests to the filestream API.
//
// It ingests a channel of requests and outputs a channel of API responses.
//
// Requests are batched to reduce the total number of HTTP requests.
// An empty "heartbeat" request is sent when there are no updates for too long,
// guaranteeing that a request is sent at least once every period specified
// by `heartbeatStopwatch`.
func (fs *fileStream) startTransmitting(
	requests <-chan *FileStreamRequest,
	initialOffsets FileStreamOffsetMap,
) <-chan map[string]any {
	maxRequestSizeBytes := fs.settings.GetFileStreamMaxBytes()
	if maxRequestSizeBytes <= 0 {
		maxRequestSizeBytes = 10 << 20 // 10 MB
	}

	transmissions := CollectLoop{
		TransmitRateLimit:   fs.transmitRateLimit,
		MaxRequestSizeBytes: int(maxRequestSizeBytes),
	}.Start(requests)

	feedback := TransmitLoop{
		HeartbeatStopwatch:     fs.heartbeatStopwatch,
		Send:                   fs.send,
		LogFatalAndStopWorking: fs.logFatalAndStopWorking,
	}.Start(transmissions, initialOffsets)

	return feedback
}

// startProcessingFeedback processes feedback from the filestream API.
//
// This increments the wait group and decrements it after completing
// all work.
func (fs *fileStream) startProcessingFeedback(
	feedback <-chan map[string]any,
	wg *sync.WaitGroup,
) {
	wg.Add(1)
	go func() {
		defer wg.Done()

		for range feedback {
		}
	}()
}

func (fs *fileStream) send(
	data *FileStreamRequestJSON,
	feedbackChan chan<- map[string]any,
) error {
	// Stop working after death to avoid data corruption.
	if fs.isDead() {
		return fmt.Errorf("filestream: can't send because I am dead")
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("filestream: json marshal error in send(): %v", err)
	}
	fs.logger.Debug("filestream: post request", "request", string(jsonData))

	req := &api.Request{
		Method: http.MethodPost,
		Path:   fs.path,
		Body:   jsonData,
		Headers: map[string]string{
			"Content-Type": "application/json",
		},
	}

	resp, err := fs.apiClient.Send(req)

	switch {
	case err != nil:
		return fmt.Errorf(
			"filestream: error making HTTP request: %v. got response: %v",
			err,
			resp,
		)
	case resp == nil:
		// Sometimes resp and err can both be nil in retryablehttp's Client.
		return fmt.Errorf("filestream: nil response and nil error for request to %v", req.Path)
	case resp.StatusCode < 200 || resp.StatusCode > 300:
		// If we reach here, that means all retries were exhausted. This could
		// mean, for instance, that the user's internet connection broke.
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<10))
		_ = resp.Body.Close()

		return fmt.Errorf(
			"filestream: failed to upload: %v path=%v: %s",
			resp.Status,
			req.Path,
			string(body),
		)
	}

	defer func(Body io.ReadCloser) {
		if err = Body.Close(); err != nil {
			fs.logger.CaptureError(
				fmt.Errorf("filestream: error closing response body: %v", err))
		}
	}(resp.Body)

	var res map[string]interface{}
	err = json.NewDecoder(resp.Body).Decode(&res)
	if err != nil {
		fs.logger.CaptureError(
			fmt.Errorf("filestream: json decode error: %v", err))
	}
	feedbackChan <- res
	fs.logger.Debug("filestream: post response", "response", res)
	return nil
}
