package monitor

import (
	"fmt"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"github.com/prometheus/common/expfmt"
)

// OpenMetrics is a monitor that collects metrics from an OpenMetrics endpoint.
//
// Supports only GAUGE and COUNTER metrics.
type OpenMetrics struct {
	name   string
	url    string
	client *retryablehttp.Client
	logger *observability.CoreLogger
}

func NewOpenMetrics(logger *observability.CoreLogger, name string, url string) *OpenMetrics {
	retryClient := retryablehttp.NewClient()
	retryClient.Logger = logger
	retryClient.CheckRetry = filetransfer.FileTransferRetryPolicy
	retryClient.RetryMax = filetransfer.DefaultRetryMax
	retryClient.RetryWaitMin = filetransfer.DefaultRetryWaitMin
	retryClient.RetryWaitMax = filetransfer.DefaultRetryWaitMax
	retryClient.HTTPClient.Timeout = filetransfer.DefaultNonRetryTimeout
	retryClient.Backoff = clients.ExponentialBackoffWithJitter

	// metrics are collected on a best-effort basis.
	retryClient.RetryMax = 3
	retryClient.RetryWaitMin = 1 * time.Second
	retryClient.RetryWaitMax = 10 * time.Second
	retryClient.HTTPClient.Timeout = 5 * time.Second

	om := &OpenMetrics{
		name:   name,
		url:    url,
		client: retryClient,
		logger: logger,
	}

	return om
}

func (o *OpenMetrics) Name() string { return o.name }

func (o *OpenMetrics) Sample() (map[string]any, error) {
	resp, err := o.client.Get(o.url)
	if err != nil {
		return nil, err
	}
	if resp != nil {
		defer resp.Body.Close()
	}

	if resp != nil && resp.StatusCode == 200 {
		var parser expfmt.TextParser
		metricFamilies, err := parser.TextToMetricFamilies(resp.Body)
		if err != nil {
			fmt.Printf("Error parsing metrics: %v\n", err)
			return nil, err
		}

		// Process the metrics
		for name, mf := range metricFamilies {
			fmt.Printf("Metric Name: %s\n", name)
			for _, m := range mf.Metric {
				fmt.Printf("  Labels: %v\n", m.Label)
				if m.Gauge != nil {
					fmt.Printf("  Gauge Value: %v\n", *m.Gauge.Value)
				}
				if m.Counter != nil {
					fmt.Printf("  Counter Value: %v\n", *m.Counter.Value)
				}
			}
			fmt.Println()
		}
	}

	return nil, nil
}

func (o *OpenMetrics) IsAvailable() bool {
	// try to fetch the metrics once to check if the endpoint is available
	_, err := o.Sample()
	if err != nil {
		o.logger.Warn(
			"openmetrics: failed to fetch metrics from endpoint",
			"url", o.url,
			"error", err,
		)
		return false
	}
	return true
}

func (o *OpenMetrics) Probe() *spb.MetadataRequest {
	return nil
}
