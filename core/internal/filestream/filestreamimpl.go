package filestream

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/filestreamstats"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
				Stats:   fs.stats,
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
	state := &FileStreamState{
		MaxRequestSizeBytes: max(
			int(fs.settings.GetFileStreamMaxBytes()),
			defaultMaxRequestSizeBytes,
		),
		MaxFileLineSize: max(
			int(fs.settings.GetFileStreamMaxLineBytes()),
			defaultMaxFileLineBytes,
		),
	}

	if initialOffsets != nil {
		state.HistoryLineNum = initialOffsets[HistoryChunk]
		state.EventsLineNum = initialOffsets[EventsChunk]
		state.SummaryLineNum = initialOffsets[SummaryChunk]
		state.ConsoleLineOffset = initialOffsets[OutputChunk]
	}

	transmissions := CollectLoop{
		Logger:            fs.logger,
		Printer:           fs.printer,
		TransmitRateLimit: fs.transmitRateLimit,
	}.Start(state, requests)

	feedback := TransmitLoop{
		HeartbeatPeriod:        fs.heartbeatPeriod,
		Send:                   fs.send,
		LogFatalAndStopWorking: fs.logFatalAndStopWorking,
	}.Start(transmissions)

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

		for res := range feedback {
			if v, ok := res["stopped"]; ok {
				if stopped, ok := v.(bool); ok && stopped {
					fs.stopState.Store(true)
				}
			}
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

	op := fs.trackUploadOperation(data)
	defer op.Finish()
	ctx := fs.requestContext(op)

	var report filestreamstats.RequestReport
	req, err := fs.prepareRequest(ctx, data, &report)
	if err != nil {
		return err
	}

	isHeartbeat := data.IsHeartbeat()
	shouldLogStartAndEnd := !isHeartbeat
	if shouldLogStartAndEnd {
		fs.logRequestSummary(data)
	}

	httpStart := time.Now()
	resp, err := fs.apiClient.Do(req)
	if err != nil {
		return fmt.Errorf("filestream: failed to send: %v", err)
	}
	defer resp.Body.Close()

	if !isHeartbeat { // Heartbeats are not interesting to track.
		report.HTTPDuration = time.Since(httpStart)
		fs.stats.RecordRequest(ctx, report)
	}

	if resp.StatusCode < 200 || resp.StatusCode > 300 {
		// If we reach here, that means all retries were exhausted. This could
		// mean, for instance, that the user's internet connection broke.
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<10))

		return fmt.Errorf(
			"filestream: failed to upload: %v url=%v: %s",
			resp.Status,
			req.URL,
			string(body),
		)
	}

	if shouldLogStartAndEnd {
		// Log after sending to record that the backend responded and should
		// have the data in the request.
		fs.logger.Info("filestream: request sent", "status", resp.Status)
	}

	fs.recordSuccessOrigin(resp)

	var res map[string]any
	err = json.NewDecoder(resp.Body).Decode(&res)
	if err != nil {
		// We don't fail (and stop uploading) if we can't parse the response,
		// as the responses are mostly informational.
		fs.logger.CaptureError("filestream",
			fmt.Errorf("filestream: json decode error: %v", err))
	} else {
		fs.logger.Debug("filestream: post response", "response", res)
		feedbackChan <- res
	}

	return nil
}

// requestContext returns the context for a filestream request tracked by op.
//
// The context lets RetryPolicy retry 404s that lack the server's
// response-origin header if shouldRetryUnmarked404s allows it.
func (fs *fileStream) requestContext(
	op *wboperation.WandbOperation,
) context.Context {
	ctx := op.Context(fs.beforeRunEndCtx)
	if !fs.shouldRetryUnmarked404s() {
		return ctx
	}

	return withUnmarked404Retry(ctx, fs.unmarked404RetryDeadline, fs.logger)
}

// shouldRetryUnmarked404s reports whether the next request should retry 404s
// that lack the server's response-origin header.
//
// That requires all of:
//
//   - a positive deadline
//   - a successful request in this run that carried the header, which shows
//     the header reaches this client
//   - the RESPONSE_ORIGIN_HEADER server feature, which old servers don't list
//     and which the server can turn off
//
// Otherwise, a 404 stops uploads as before.
func (fs *fileStream) shouldRetryUnmarked404s() bool {
	return fs.unmarked404RetryDeadline > 0 &&
		fs.sawMarkedSuccess.Load() &&
		fs.featureProvider.Enabled(
			fs.beforeRunEndCtx,
			spb.ServerFeature_RESPONSE_ORIGIN_HEADER,
		)
}

// recordSuccessOrigin records whether a successful response carried the
// server's response-origin header.
func (fs *fileStream) recordSuccessOrigin(resp *http.Response) {
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return
	}

	if api.HasServerHeader(resp) && !fs.sawMarkedSuccess.Swap(true) {
		fs.logger.Info(
			"filestream: server marks its responses with the" +
				" response-origin header")
	}
}

// prepareRequest creates the FileStream request.
//
// On success, it sets all fields of RequestReport other than HTTPDuration.
func (fs *fileStream) prepareRequest(
	ctx context.Context,
	data *FileStreamRequestJSON,
	report *filestreamstats.RequestReport,
) (*retryablehttp.Request, error) {
	jsonData, err := fs.jsonMarshalTimed(data)
	if err != nil {
		return nil, fmt.Errorf(
			"filestream: json marshal error in send(): %v", err)
	}
	fs.logger.Debug("filestream: post request", "request", string(jsonData))

	useGzip := fs.settings.IsFileStreamGzipEnabled() &&
		fs.featureProvider.Enabled(ctx, spb.ServerFeature_FILESTREAM_GZIP)

	requestBody := jsonData
	if useGzip {
		compressed, err := fs.gzipTimed(jsonData)
		if err != nil {
			return nil, fmt.Errorf("filestream: compress request: %v", err)
		}
		requestBody = compressed
	}

	req, err := retryablehttp.NewRequestWithContext(
		ctx,
		http.MethodPost,
		fs.baseURL.JoinPath(fs.path).String(),
		bytes.NewReader(requestBody),
	)
	if err != nil {
		return nil, fmt.Errorf("filestream: error constructing request: %v", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if useGzip {
		req.Header.Set("Content-Encoding", "gzip")
	}
	if fs.segmentID != "" {
		req.Header.Set("X-Wandb-Segment-ID", fs.segmentID)
	}

	report.UncompressedBytes = len(jsonData)
	report.CompressedBytes = len(requestBody)
	report.Compressed = useGzip
	return req, nil
}

// jsonMarshalTimed calls json.Marshal() and tracks how long it takes.
func (fs *fileStream) jsonMarshalTimed(
	data *FileStreamRequestJSON,
) ([]byte, error) {
	marshalStart := time.Now()

	encoded, err := json.Marshal(data)
	if err != nil {
		return nil, err
	}

	fs.stats.RecordSegment(
		fs.beforeRunEndCtx,
		filestreamstats.SegmentRequestMarshal,
		filestreamstats.StreamNone,
		time.Since(marshalStart),
	)

	return encoded, nil
}

// gzipTimed compresses the data and tracks how long it takes.
//
// We compress all at once, instead of as the request is being sent,
// because the full request must be stored in memory anyway to support retries.
func (fs *fileStream) gzipTimed(data []byte) ([]byte, error) {
	compressStart := time.Now()

	var compressed bytes.Buffer
	gzipWriter := gzip.NewWriter(&compressed)
	if _, err := gzipWriter.Write(data); err != nil {
		return nil, err
	}
	if err := gzipWriter.Close(); err != nil {
		return nil, err
	}

	fs.stats.RecordSegment(
		fs.beforeRunEndCtx,
		filestreamstats.SegmentRequestCompress,
		filestreamstats.StreamNone,
		time.Since(compressStart),
	)

	return compressed.Bytes(), nil
}

// trackUploadOperation returns a WandbOperation for tracking
// a filestream upload.
func (fs *fileStream) trackUploadOperation(
	data *FileStreamRequestJSON,
) *wboperation.WandbOperation {
	parts := make([]string, 0, 3)

	if history, ok := data.Files[HistoryFileName]; ok && len(history.Content) > 0 {
		parts = append(parts,
			fmt.Sprintf("history steps %d-%d",
				history.Offset,
				history.Offset+len(history.Content)-1))
	}

	if summary, ok := data.Files[SummaryFileName]; ok && len(summary.Content) > 0 {
		parts = append(parts, "summary")
	}

	if console, ok := data.Files[OutputFileName]; ok && len(console.Content) > 0 {
		parts = append(parts,
			fmt.Sprintf("console lines %d-%d",
				console.Offset,
				console.Offset+len(console.Content)-1))
	}

	if len(parts) == 0 {
		// Shouldn't happen, but guard against future bugs.
		return fs.operations.New("uploading data")
	} else {
		return fs.operations.New("uploading " + strings.Join(parts, ", "))
	}
}

// logRequestSummary logs a little information about a request at INFO level.
//
// When metrics don't show up in the UI, this helps determine whether they were
// even sent.
func (fs *fileStream) logRequestSummary(data *FileStreamRequestJSON) {
	// 11 = number of attribute pairs logged below
	attrs := make([]any, 0, 11*2)

	attrs = append(attrs, "total_files", len(data.Files))

	if history, ok := data.Files[HistoryFileName]; ok {
		attrs = append(attrs,
			"history_offset", history.Offset,
			"history_lines", len(history.Content))
	}
	if events, ok := data.Files[EventsFileName]; ok {
		attrs = append(attrs,
			"events_offset", events.Offset,
			"events_lines", len(events.Content))
	}
	if console, ok := data.Files[OutputFileName]; ok {
		attrs = append(attrs,
			"console_offset", console.Offset,
			"console_lines", len(console.Content))
	}

	if len(data.Uploaded) > 0 {
		attrs = append(attrs, "uploaded_len", len(data.Uploaded))
	}

	if data.Preempting != nil {
		attrs = append(attrs, "preempting", *data.Preempting)
	}
	if data.Complete != nil {
		attrs = append(attrs, "complete", *data.Complete)
	}
	if data.ExitCode != nil {
		attrs = append(attrs, "exit_code", *data.ExitCode)
	}

	fs.logger.Info("filestream: sending request", attrs...)
}
