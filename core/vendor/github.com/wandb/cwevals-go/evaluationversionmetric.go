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

// EvaluationVersionMetricService contains methods and other services that help
// with interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationVersionMetricService] method instead.
type EvaluationVersionMetricService struct {
	Options []option.RequestOption
}

// NewEvaluationVersionMetricService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationVersionMetricService(opts ...option.RequestOption) (r *EvaluationVersionMetricService) {
	r = &EvaluationVersionMetricService{}
	r.Options = opts
	return
}

// Returns the newest reported value for each subject and metric name at this
// evaluation version's `last_commit_id`. The response exposes that cutoff as
// `published_commit_id`.
//
// Values reported after the version was created are not included.
func (r *EvaluationVersionMetricService) List(
	ctx context.Context,
	evaluationVersionID string,
	query EvaluationVersionMetricListParams,
	opts ...option.RequestOption,
) (res *EvaluationVersionMetricListResponse, err error) {
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
	if evaluationVersionID == "" {
		err = errors.New("missing required evaluation_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluation-versions/%s/metrics",
		query.Namespace,
		query.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type EvaluationVersionMetricListResponse struct {
	// Newest value per subject and name, ordered by subject and then name. Values
	// without a subject come first.
	Metrics []EvaluationVersionMetricListResponseMetric `json:"metrics" api:"required"`
	// Publication cutoff used to select the returned metric values.
	PublishedCommitID int64                                   `json:"published_commit_id" api:"required"`
	JSON              evaluationVersionMetricListResponseJSON `json:"-"`
}

// evaluationVersionMetricListResponseJSON contains the JSON metadata for the
// struct [EvaluationVersionMetricListResponse]
type evaluationVersionMetricListResponseJSON struct {
	Metrics           apijson.Field
	PublishedCommitID apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationVersionMetricListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionMetricListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionMetricListResponseMetric struct {
	CommitID  int64                                               `json:"commit_id"  api:"required"`
	Name      string                                              `json:"name"       api:"required"`
	Subject   string                                              `json:"subject"    api:"required,nullable"`
	Value     interface{}                                         `json:"value"      api:"required"`
	ValueType EvaluationVersionMetricListResponseMetricsValueType `json:"value_type" api:"required"`
	JSON      evaluationVersionMetricListResponseMetricJSON       `json:"-"`
}

// evaluationVersionMetricListResponseMetricJSON contains the JSON metadata for the
// struct [EvaluationVersionMetricListResponseMetric]
type evaluationVersionMetricListResponseMetricJSON struct {
	CommitID    apijson.Field
	Name        apijson.Field
	Subject     apijson.Field
	Value       apijson.Field
	ValueType   apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionMetricListResponseMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionMetricListResponseMetricJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionMetricListResponseMetricsValueType string

const (
	EvaluationVersionMetricListResponseMetricsValueTypeBoolean EvaluationVersionMetricListResponseMetricsValueType = "boolean"
	EvaluationVersionMetricListResponseMetricsValueTypeNumber  EvaluationVersionMetricListResponseMetricsValueType = "number"
	EvaluationVersionMetricListResponseMetricsValueTypeString  EvaluationVersionMetricListResponseMetricsValueType = "string"
	EvaluationVersionMetricListResponseMetricsValueTypeJson    EvaluationVersionMetricListResponseMetricsValueType = "json"
)

func (r EvaluationVersionMetricListResponseMetricsValueType) IsKnown() bool {
	switch r {
	case EvaluationVersionMetricListResponseMetricsValueTypeBoolean,
		EvaluationVersionMetricListResponseMetricsValueTypeNumber,
		EvaluationVersionMetricListResponseMetricsValueTypeString,
		EvaluationVersionMetricListResponseMetricsValueTypeJson:
		return true
	}
	return false
}

type EvaluationVersionMetricListParams struct {
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
