package filestream

import (
	"fmt"
	"io"
	"math"
	"net/http"
)

// completionOnly drops data that the server will reject for a blocked run.
func completionOnly(data *FileStreamRequestJSON) *FileStreamRequestJSON {
	if data.Complete == nil || !*data.Complete {
		return nil
	}
	return &FileStreamRequestJSON{
		Complete: data.Complete,
		ExitCode: data.ExitCode,
	}
}

func (fs *fileStream) handleUploadError(
	data *FileStreamRequestJSON,
	feedbackChan chan<- map[string]any,
	resp *http.Response,
	requestURL string,
) error {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<10))
	_ = resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest ||
		resp.Header.Get("X-Wandb-Error-Code") != "run_metric_limit_exceeded" ||
		fs.metricLimitBlocked {
		return fmt.Errorf(
			"filestream: failed to upload: %v url=%v: %s",
			resp.Status, requestURL, string(body),
		)
	}

	fs.metricLimitBlocked = true
	fs.printer.Errorf(
		"Run metric limit exceeded. Further filestream uploads for this run" +
			" have stopped. Previously accepted data remains available, and" +
			" run data continues to be saved locally. Start a new run with" +
			" fewer metric names or contact support.",
	)
	fs.logger.Error("filestream: run metric limit exceeded", "response", string(body))
	if fs.settings.IsStopOnFatalError() {
		fs.stopState.Store(true)
	}

	// Keep the transmit loop alive for completion. If the rejected request
	// already included completion, retry once with only its control fields.
	if completion := completionOnly(data); completion != nil {
		return fs.send(completion, feedbackChan)
	}
	return nil
}

func (fs *fileStream) warnMetricLimit(response map[string]any) {
	if fs.metricLimitWarned {
		return
	}
	status, ok := response["metric_limit"].(map[string]any)
	if !ok {
		return
	}
	warning, _ := status["warning"].(bool)
	count, countOK := status["count"].(float64)
	limit, limitOK := status["limit"].(float64)
	if !warning || !countOK || !limitOK || count < 0 || limit <= 0 ||
		math.Trunc(count) != count || math.Trunc(limit) != limit {
		return
	}
	fs.metricLimitWarned = true
	fs.printer.Warnf(
		"Run is approaching its metric limit: %.0f of %.0f distinct metric"+
			" names observed so far. Exceeding the limit stops further filestream"+
			" uploads for this run.",
		count, limit,
	)
}
