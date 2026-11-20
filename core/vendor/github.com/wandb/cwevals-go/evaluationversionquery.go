// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"github.com/wandb/cwevals-go/option"
)

// EvaluationVersionQueryService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationVersionQueryService] method instead.
type EvaluationVersionQueryService struct {
	Options []option.RequestOption
	Results *EvaluationVersionQueryResultService
}

// NewEvaluationVersionQueryService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationVersionQueryService(opts ...option.RequestOption) (r *EvaluationVersionQueryService) {
	r = &EvaluationVersionQueryService{}
	r.Options = opts
	r.Results = NewEvaluationVersionQueryResultService(opts...)
	return
}
