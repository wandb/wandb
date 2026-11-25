// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"slices"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// EvaluationMetricService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationMetricService] method instead.
type EvaluationMetricService struct {
	Options []option.RequestOption
}

// NewEvaluationMetricService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationMetricService(opts ...option.RequestOption) (r *EvaluationMetricService) {
	r = &EvaluationMetricService{}
	r.Options = opts
	return
}

// Returns the newest reported value for each subject and metric name at the
// scope's latest published commit. The next evaluation version freezes these
// values.
//
// For metrics calculated by aggregating individual scores, use the saved query
// results operations instead.
func (r *EvaluationMetricService) List(
	ctx context.Context,
	evaluationID string,
	query EvaluationMetricListParams,
	opts ...option.RequestOption,
) (res *EvaluationMetricListResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return nil, err
	}
	requestconfig.UseDefaultParam(&query.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&query.ScopeID, precfg.ScopeID)
	if query.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return nil, err
	}
	if query.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return nil, err
	}
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/metrics",
		query.Namespace,
		query.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

// Stores metrics calculated by your application, such as FID or corpus BLEU, that
// cannot be aggregated from individual scores. A metric describes the whole
// evaluation or one named subject.
//
// **Updating values**
//
//   - Reporting the same subject and name replaces the earlier value from the new
//     commit onward. Send JSON `null` to remove it.
//   - Frozen evaluation versions retain the values at their publication cutoff. A
//     value carries into later versions until replaced or removed.
//   - The service does not track which cases or scores you used to calculate the
//     metric.
//
// **Value types**
//
// Types are inferred from JSON. All JSON numbers use `number`. Objects and arrays
// use `json`. A metric name keeps the type of its first value across all subjects.
// Reporting another type returns 400 with the conflict.
//
// **Storage limits**
//
// An evaluation can hold at most 10,000 metrics and 4 MiB of metric subjects,
// names, and values at once. A report that exceeds either limit is rejected.
// Replacing or removing values frees space.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationMetricService) Report(
	ctx context.Context,
	evaluationID string,
	params EvaluationMetricReportParams,
	opts ...option.RequestOption,
) (res *EvaluationMetricReportResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return nil, err
	}
	requestconfig.UseDefaultParam(&params.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&params.ScopeID, precfg.ScopeID)
	if params.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return nil, err
	}
	if params.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return nil, err
	}
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/metrics",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvaluationMetricListResponse struct {
	// Newest value per subject and name, ordered by subject and then name. Values
	// without a subject come first.
	Metrics []EvaluationMetricListResponseMetric `json:"metrics" api:"required"`
	// Publication cutoff used to select the returned metric values.
	PublishedCommitID int64                            `json:"published_commit_id" api:"required"`
	JSON              evaluationMetricListResponseJSON `json:"-"`
}

// evaluationMetricListResponseJSON contains the JSON metadata for the struct
// [EvaluationMetricListResponse]
type evaluationMetricListResponseJSON struct {
	Metrics           apijson.Field
	PublishedCommitID apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationMetricListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationMetricListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationMetricListResponseMetric struct {
	CommitID  int64                                        `json:"commit_id"  api:"required"`
	Name      string                                       `json:"name"       api:"required"`
	Subject   string                                       `json:"subject"    api:"required,nullable"`
	Value     interface{}                                  `json:"value"      api:"required"`
	ValueType EvaluationMetricListResponseMetricsValueType `json:"value_type" api:"required"`
	JSON      evaluationMetricListResponseMetricJSON       `json:"-"`
}

// evaluationMetricListResponseMetricJSON contains the JSON metadata for the struct
// [EvaluationMetricListResponseMetric]
type evaluationMetricListResponseMetricJSON struct {
	CommitID    apijson.Field
	Name        apijson.Field
	Subject     apijson.Field
	Value       apijson.Field
	ValueType   apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationMetricListResponseMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationMetricListResponseMetricJSON) RawJSON() string {
	return r.raw
}

type EvaluationMetricListResponseMetricsValueType string

const (
	EvaluationMetricListResponseMetricsValueTypeBoolean EvaluationMetricListResponseMetricsValueType = "boolean"
	EvaluationMetricListResponseMetricsValueTypeNumber  EvaluationMetricListResponseMetricsValueType = "number"
	EvaluationMetricListResponseMetricsValueTypeString  EvaluationMetricListResponseMetricsValueType = "string"
	EvaluationMetricListResponseMetricsValueTypeJson    EvaluationMetricListResponseMetricsValueType = "json"
)

func (r EvaluationMetricListResponseMetricsValueType) IsKnown() bool {
	switch r {
	case EvaluationMetricListResponseMetricsValueTypeBoolean,
		EvaluationMetricListResponseMetricsValueTypeNumber,
		EvaluationMetricListResponseMetricsValueTypeString,
		EvaluationMetricListResponseMetricsValueTypeJson:
		return true
	}
	return false
}

type EvaluationMetricReportResponse struct {
	// Commit that recorded this report. An evaluation version includes these values if
	// its last_commit_id is at least this commit.
	CommitID     int64                              `json:"commit_id"     api:"required"`
	EvaluationID string                             `json:"evaluation_id" api:"required" format:"uuid"`
	JSON         evaluationMetricReportResponseJSON `json:"-"`
}

// evaluationMetricReportResponseJSON contains the JSON metadata for the struct
// [EvaluationMetricReportResponse]
type evaluationMetricReportResponseJSON struct {
	CommitID     apijson.Field
	EvaluationID apijson.Field
	raw          string
	ExtraFields  map[string]apijson.Field
}

func (r *EvaluationMetricReportResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationMetricReportResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationMetricListParams struct {
	// Namespace that assigned the scope reference.
	//
	// Defaults to "wandb" if not set.
	Namespace param.Field[string] `path:"namespace" api:"required"`
	// Project reference assigned by the namespace. For wandb, use the internal W&B
	// project ID, not the project name or entity/project path.
	//
	// Percent-encode reserved characters so the reference occupies one URL path
	// segment. Only printable ASCII is accepted. References are compared exactly,
	// without parsing.
	//
	// Use [option.WithScopeID] on the client to set a global default for this field.
	ScopeID param.Field[string] `path:"scope_id" api:"required"`
}

type EvaluationMetricReportParams struct {
	// Namespace that assigned the scope reference.
	//
	// Defaults to "wandb" if not set.
	Namespace param.Field[string] `path:"namespace" api:"required"`
	// Project reference assigned by the namespace. For wandb, use the internal W&B
	// project ID, not the project name or entity/project path.
	//
	// Percent-encode reserved characters so the reference occupies one URL path
	// segment. Only printable ASCII is accepted. References are compared exactly,
	// without parsing.
	//
	// Use [option.WithScopeID] on the client to set a global default for this field.
	ScopeID param.Field[string]                               `path:"scope_id" api:"required"`
	Metrics param.Field[[]EvaluationMetricReportParamsMetric] `                api:"required" json:"metrics"`
}

func (r EvaluationMetricReportParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvaluationMetricReportParamsMetric struct {
	Name param.Field[string] `json:"name" api:"required"`
	// Metric value calculated by your application, in any JSON type. Send JSON null to
	// remove this metric from this commit onward.
	Value param.Field[interface{}] `json:"value" api:"required"`
	// Model, checkpoint, or other entity the metric describes. Leading and trailing
	// whitespace are not allowed. Omit or send null for a metric describing the whole
	// evaluation.
	Subject param.Field[string] `json:"subject"`
}

func (r EvaluationMetricReportParamsMetric) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
