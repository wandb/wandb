package runevents

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"time"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	maxPendingEvents = 10_000
	maxBatchEvents   = 100
	maxBatchBytes    = 512 * 1024
	batchInterval    = 2 * time.Second
	retryTimeout     = 5 * time.Minute
	batchSuffix      = "]}"
)

type Params struct {
	BaseURL     api.WBBaseURL
	Project     string
	RunID       string
	Logger      *observability.CoreLogger
	Printer     *observability.Printer
	HTTPOptions api.ClientOptions
}

// Uploader batches events for a single run without blocking on uploads.
type Uploader struct {
	ctx         context.Context
	client      api.RetryableClient
	endpoint    string
	runID       string
	batchPrefix string
	logger      *observability.CoreLogger
	printer     *observability.Printer
	done        chan struct{}

	mu         sync.Mutex
	queue      chan []byte
	pending    int
	warnedFull bool
}

func New(ctx context.Context, params Params) *Uploader {
	params.HTTPOptions.RetryMax = api.DefaultRetryMax
	params.HTTPOptions.Logger = params.Logger.Logger
	params.HTTPOptions.RetryPolicy = func(ctx context.Context, resp *http.Response, err error) (bool, error) {
		if err != nil || ctx.Err() != nil {
			return clients.CheckRetry(ctx, resp, err)
		}
		status := resp.StatusCode
		return status == http.StatusTooManyRequests || (status >= 500 && status <= 599), nil
	}
	project, _ := json.Marshal(params.Project)
	u := &Uploader{
		ctx:         ctx,
		client:      api.NewClient(params.HTTPOptions),
		endpoint:    (*url.URL)(params.BaseURL).JoinPath("logs/ingest").String(),
		runID:       params.RunID,
		batchPrefix: `{"project":` + string(project) + `,"records":[`,
		logger:      params.Logger,
		printer:     params.Printer,
		queue:       make(chan []byte, maxPendingEvents),
		done:        make(chan struct{}),
	}
	go u.run(u.queue)
	return u
}

type ingestRecord struct {
	EventID    string                     `json:"event_id"`
	Run        string                     `json:"run"`
	Timestamp  int64                      `json:"timestamp"`
	Message    string                     `json:"message"`
	Attributes map[string]ingestAttribute `json:"attributes"`
}

type ingestAttribute struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

func floatAttribute(value float64) ingestAttribute {
	// The server's canonical float encoding uses positive zero.
	return ingestAttribute{"float64", strconv.FormatFloat(value+0, 'g', -1, 64)}
}

// Enqueue keeps a snapshot of the event if the uploader has room for it.
func (u *Uploader) Enqueue(event *spb.EventRecord) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.queue == nil || event == nil || u.ctx.Err() != nil {
		return
	}
	if u.pending == maxPendingEvents {
		if !u.warnedFull {
			u.printer.Warnf("Event logging queue is full. Dropping new events.")
			u.warnedFull = true
		}
		return
	}

	attributes := make(map[string]ingestAttribute, len(event.GetAttributes())+6)
	for name, attribute := range event.GetAttributes() {
		switch v := attribute.GetValue().(type) {
		case *spb.EventAttributeValue_StringValue:
			attributes[name] = ingestAttribute{"string", v.StringValue}
		case *spb.EventAttributeValue_IntValue:
			attributes[name] = ingestAttribute{"int64", strconv.FormatInt(v.IntValue, 10)}
		case *spb.EventAttributeValue_DoubleValue:
			attributes[name] = floatAttribute(v.DoubleValue)
		case *spb.EventAttributeValue_BoolValue:
			attributes[name] = ingestAttribute{"bool", strconv.FormatBool(v.BoolValue)}
		}
	}
	attributes["step"] = ingestAttribute{"int64", strconv.FormatInt(event.GetStep(), 10)}
	attributes["severity"] = ingestAttribute{"string", event.GetSeverity()}
	attributes["event_type"] = ingestAttribute{"string", event.GetType()}
	attributes["source_sdk"] = ingestAttribute{"string", "wandb-python"}
	if event.StepMetricValue != nil {
		attributes["step_metric"] = ingestAttribute{"string", event.GetStepMetric()}
		attributes["step_metric_value"] = floatAttribute(event.GetStepMetricValue())
	}

	body, err := json.Marshal(ingestRecord{
		EventID:    event.GetEventId(),
		Run:        u.runID,
		Timestamp:  event.GetTimestampMs() * int64(time.Millisecond),
		Message:    event.GetTitle(),
		Attributes: attributes,
	})
	if err != nil {
		u.logger.Warn("runevents: failed to encode event", "error", err)
		return
	}
	if len(u.batchPrefix)+len(body)+len(batchSuffix) > maxBatchBytes {
		u.logger.Warn("runevents: dropped event larger than the upload limit", "bytes", len(body))
		return
	}
	u.pending++
	u.queue <- body
}

// Finish flushes accepted events and waits for the uploader to stop.
func (u *Uploader) Finish() {
	u.closeQueue()
	<-u.done
}

func (u *Uploader) closeQueue() {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.queue != nil {
		close(u.queue)
		u.queue = nil
	}
}

type eventBatch struct {
	bytes.Buffer
	count int
}

func (u *Uploader) run(queue <-chan []byte) {
	defer u.logger.Reraise("runevents")
	defer close(u.done)
	defer u.closeQueue()

	ticker := time.NewTicker(batchInterval)
	defer ticker.Stop()
	var batch eventBatch
	batch.WriteString(u.batchPrefix)

	for keepUploading := true; keepUploading && u.ctx.Err() == nil; {
		var event []byte
		select {
		case <-u.ctx.Done():
			return
		case <-ticker.C:
			keepUploading = u.upload(&batch)
			continue
		case event = <-queue:
		}
		if event == nil {
			u.upload(&batch)
			return
		}
		if batch.Len()+len(event)+len(batchSuffix) > maxBatchBytes && !u.upload(&batch) {
			return
		}
		batch.Write(event)
		batch.WriteByte(',')
		batch.count++
		if batch.count == maxBatchEvents || batch.Len()-1+len(batchSuffix) == maxBatchBytes {
			keepUploading = u.upload(&batch)
		}
	}
}

func (u *Uploader) upload(batch *eventBatch) bool {
	if batch.count == 0 {
		return true
	}
	defer func() {
		u.mu.Lock()
		u.pending -= batch.count
		u.mu.Unlock()
		// The transport can still hold the previous request body.
		batch.Buffer = bytes.Buffer{}
		batch.WriteString(u.batchPrefix)
		batch.count = 0
	}()
	batch.Truncate(batch.Len() - 1)
	batch.WriteString(batchSuffix)

	ctx, cancel := context.WithTimeout(u.ctx, retryTimeout)
	defer cancel()
	req, err := retryablehttp.NewRequestWithContext(ctx, http.MethodPost, u.endpoint, batch.Bytes())
	if err != nil {
		u.logger.Warn("runevents: failed to build request", "error", err)
		return true
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := u.client.Do(req)
	if err != nil {
		u.logger.Warn(
			"runevents: failed to upload event batch",
			"error",
			err,
			"events",
			batch.count,
		)
		return true
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	switch resp.StatusCode {
	case http.StatusAccepted:
		return true
	case http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound:
		u.printer.Warnf(
			"Event logging is disabled for this project. Events will stay in the local run log.",
		)
		return false
	default:
		u.logger.Warn(
			"runevents: dropped event batch",
			"status",
			resp.StatusCode,
			"events",
			batch.count,
		)
		return true
	}
}
