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

// DatasetCaseService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetCaseService] method instead.
type DatasetCaseService struct {
	Options []option.RequestOption
}

// NewDatasetCaseService generates a new service that applies the given options to
// each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewDatasetCaseService(opts ...option.RequestOption) (r *DatasetCaseService) {
	r = &DatasetCaseService{}
	r.Options = opts
	return
}

// Stores a batch of cases. Each case contains an input, an output, and optional
// metadata, such as the model or checkpoint that produced the output.
//
// Top-level fields in input and output objects are added to the dataset's field
// catalog. The response returns case IDs in request order.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetCaseService) Add(
	ctx context.Context,
	datasetID string,
	params DatasetCaseAddParams,
	opts ...option.RequestOption,
) (res *DatasetCaseAddResponse, err error) {
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
	if datasetID == "" {
		err = errors.New("missing required dataset_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets/%s/cases", params.Namespace, params.ScopeID, datasetID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPatch, path, params, &res, opts...)
	return res, err
}

type DatasetCaseAddResponse struct {
	CaseIDs            []string                   `json:"case_ids"             api:"required" format:"uuid"`
	CommitID           int64                      `json:"commit_id"            api:"required"`
	PublishOperationID string                     `json:"publish_operation_id" api:"required" format:"uuid"`
	JSON               datasetCaseAddResponseJSON `json:"-"`
}

// datasetCaseAddResponseJSON contains the JSON metadata for the struct
// [DatasetCaseAddResponse]
type datasetCaseAddResponseJSON struct {
	CaseIDs            apijson.Field
	CommitID           apijson.Field
	PublishOperationID apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *DatasetCaseAddResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetCaseAddResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetCaseAddParams struct {
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
	ScopeID param.Field[string]                     `path:"scope_id" api:"required"`
	Cases   param.Field[[]DatasetCaseAddParamsCase] `                api:"required" json:"cases"`
	// Derives an example key for each case from a hash of its input, so row comparison
	// can match cases by input. Each top-level extension field hashes by its identity,
	// which leaves out file locations. Numbers hash as float64, so integers that
	// differ only beyond 2^53 derive the same example key, and a number never matches
	// a string. Log numeric identifiers as strings. A case with a null input gets no
	// example key. Without it, a case logged without an example key matches only
	// itself, in versions that read its dataset.
	ExampleKeyFields param.Field[[]DatasetCaseAddParamsExampleKeyField] `json:"example_key_fields"`
}

func (r DatasetCaseAddParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetCaseAddParamsCase struct {
	Attributes param.Field[map[string]interface{}] `json:"attributes"`
	// Reference to the case's example in external data, such as an S3 object key or
	// row index.
	//
	// - The service stores the reference but does not fetch the example.
	// - Example keys need not be unique. Row comparison matches cases by example key.
	// - A case with no input can use this reference to identify its example.
	//
	// Omit or send null when no example reference applies. Omit on every case when the
	// request sets example_key_fields.
	ExampleKey param.Field[string] `json:"example_key"`
	// Input data for this case, such as a prompt or feature values.
	//
	// For JSON objects:
	//
	//   - Top-level field names must contain 1 to 512 Unicode characters, with no
	//     leading or trailing whitespace.
	//   - All numeric fields are inferred as number, even whole-valued literals.
	//   - Queries use float64 numbers, which can round integers beyond 2^53. The stored
	//     JSON remains exact.
	//
	// Omit to store null.
	Input param.Field[CaseValueUnionParam] `json:"input"`
	// Output recorded for this case, such as a model response.
	//
	// For JSON objects:
	//
	//   - Top-level field names must contain 1 to 512 Unicode characters, with no
	//     leading or trailing whitespace.
	//   - All numeric fields are inferred as number, even whole-valued literals.
	//   - Queries use float64 numbers, which can round integers beyond 2^53. The stored
	//     JSON remains exact.
	//
	// Omit to store null.
	Output param.Field[CaseValueUnionParam] `json:"output"`
	// Trajectory to add this case to. It must belong to the same dataset. Omit or send
	// null for a case outside any trajectory.
	TrajectoryID param.Field[string] `json:"trajectory_id" format:"uuid"`
	// Model, agent, prompt, or checkpoint this case evaluates. Leading and trailing
	// whitespace are not allowed. Omit or send null when no variant applies.
	Variant param.Field[string] `json:"variant"`
}

func (r DatasetCaseAddParamsCase) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetCaseAddParamsExampleKeyField string

const (
	DatasetCaseAddParamsExampleKeyFieldInput DatasetCaseAddParamsExampleKeyField = "input"
)

func (r DatasetCaseAddParamsExampleKeyField) IsKnown() bool {
	switch r {
	case DatasetCaseAddParamsExampleKeyFieldInput:
		return true
	}
	return false
}
