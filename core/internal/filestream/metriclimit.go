package filestream

import (
	"encoding/json"
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
	body, readErr := io.ReadAll(io.LimitReader(resp.Body, (64<<10)+1))
	_ = resp.Body.Close()

	var response struct {
		Extensions struct {
			Code     string `json:"code"`
			LimitKey string `json:"limit_key"`
		} `json:"extensions"`
	}
	if resp.StatusCode != http.StatusBadRequest || readErr != nil || len(body) > 64<<10 ||
		json.Unmarshal(body, &response) != nil ||
		response.Extensions.Code != "USAGE_LIMIT_EXCEEDED" ||
		response.Extensions.LimitKey != "distinct_metrics_per_run" ||
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
	statuses, ok := response["limit_statuses"].(map[string]any)
	if !ok {
		return
	}
	status, ok := statuses["distinct_metrics_per_run"].(map[string]any)
	if !ok {
		return
	}
	available, _ := status["available"].(bool)
	warning, _ := status["warning"].(bool)
	count, countOK := status["usage"].(float64)
	limit, limitOK := status["limit"].(float64)
	if !available || !warning || !countOK || !limitOK || count < 0 || limit <= 0 ||
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
