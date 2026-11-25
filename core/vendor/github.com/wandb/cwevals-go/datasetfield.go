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

// DatasetFieldService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetFieldService] method instead.
type DatasetFieldService struct {
	Options []option.RequestOption
}

// NewDatasetFieldService generates a new service that applies the given options to
// each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewDatasetFieldService(opts ...option.RequestOption) (r *DatasetFieldService) {
	r = &DatasetFieldService{}
	r.Options = opts
	return
}

// Declares input or output fields on the dataset's pending version so you can
// choose their types before adding cases.
//
// Repeating an identical declaration makes no change. A declaration that conflicts
// with an existing field's type is rejected.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetFieldService) New(
	ctx context.Context,
	datasetID string,
	params DatasetFieldNewParams,
	opts ...option.RequestOption,
) (res *DatasetFieldNewResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets/%s/fields", params.Namespace, params.ScopeID, datasetID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type DatasetFieldNewResponse struct {
	Fields []DatasetFieldNewResponseField `json:"fields" api:"required"`
	JSON   datasetFieldNewResponseJSON    `json:"-"`
}

// datasetFieldNewResponseJSON contains the JSON metadata for the struct
// [DatasetFieldNewResponse]
type datasetFieldNewResponseJSON struct {
	Fields      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetFieldNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetFieldNewResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetFieldNewResponseField struct {
	DatasetFieldID int64                                  `json:"dataset_field_id" api:"required"`
	Name           string                                 `json:"name"             api:"required"`
	Source         DatasetFieldNewResponseFieldsSource    `json:"source"           api:"required"`
	ValueType      DatasetFieldNewResponseFieldsValueType `json:"value_type"       api:"required"`
	JSON           datasetFieldNewResponseFieldJSON       `json:"-"`
}

// datasetFieldNewResponseFieldJSON contains the JSON metadata for the struct
// [DatasetFieldNewResponseField]
type datasetFieldNewResponseFieldJSON struct {
	DatasetFieldID apijson.Field
	Name           apijson.Field
	Source         apijson.Field
	ValueType      apijson.Field
	raw            string
	ExtraFields    map[string]apijson.Field
}

func (r *DatasetFieldNewResponseField) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetFieldNewResponseFieldJSON) RawJSON() string {
	return r.raw
}

type DatasetFieldNewResponseFieldsSource string

const (
	DatasetFieldNewResponseFieldsSourceInput  DatasetFieldNewResponseFieldsSource = "input"
	DatasetFieldNewResponseFieldsSourceOutput DatasetFieldNewResponseFieldsSource = "output"
)

func (r DatasetFieldNewResponseFieldsSource) IsKnown() bool {
	switch r {
	case DatasetFieldNewResponseFieldsSourceInput, DatasetFieldNewResponseFieldsSourceOutput:
		return true
	}
	return false
}

type DatasetFieldNewResponseFieldsValueType string

const (
	DatasetFieldNewResponseFieldsValueTypeBoolean DatasetFieldNewResponseFieldsValueType = "boolean"
	DatasetFieldNewResponseFieldsValueTypeInteger DatasetFieldNewResponseFieldsValueType = "integer"
	DatasetFieldNewResponseFieldsValueTypeNumber  DatasetFieldNewResponseFieldsValueType = "number"
	DatasetFieldNewResponseFieldsValueTypeString  DatasetFieldNewResponseFieldsValueType = "string"
	DatasetFieldNewResponseFieldsValueTypeJson    DatasetFieldNewResponseFieldsValueType = "json"
)

func (r DatasetFieldNewResponseFieldsValueType) IsKnown() bool {
	switch r {
	case DatasetFieldNewResponseFieldsValueTypeBoolean,
		DatasetFieldNewResponseFieldsValueTypeInteger,
		DatasetFieldNewResponseFieldsValueTypeNumber,
		DatasetFieldNewResponseFieldsValueTypeString,
		DatasetFieldNewResponseFieldsValueTypeJson:
		return true
	}
	return false
}

type DatasetFieldNewParams struct {
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
	ScopeID param.Field[string]                       `path:"scope_id" api:"required"`
	Fields  param.Field[[]DatasetFieldNewParamsField] `                api:"required" json:"fields"`
}

func (r DatasetFieldNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetFieldNewParamsField struct {
	Name      param.Field[string]                               `json:"name"       api:"required"`
	Source    param.Field[DatasetFieldNewParamsFieldsSource]    `json:"source"     api:"required"`
	ValueType param.Field[DatasetFieldNewParamsFieldsValueType] `json:"value_type" api:"required"`
}

func (r DatasetFieldNewParamsField) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetFieldNewParamsFieldsSource string

const (
	DatasetFieldNewParamsFieldsSourceInput  DatasetFieldNewParamsFieldsSource = "input"
	DatasetFieldNewParamsFieldsSourceOutput DatasetFieldNewParamsFieldsSource = "output"
)

func (r DatasetFieldNewParamsFieldsSource) IsKnown() bool {
	switch r {
	case DatasetFieldNewParamsFieldsSourceInput, DatasetFieldNewParamsFieldsSourceOutput:
		return true
	}
	return false
}

type DatasetFieldNewParamsFieldsValueType string

const (
	DatasetFieldNewParamsFieldsValueTypeBoolean DatasetFieldNewParamsFieldsValueType = "boolean"
	DatasetFieldNewParamsFieldsValueTypeInteger DatasetFieldNewParamsFieldsValueType = "integer"
	DatasetFieldNewParamsFieldsValueTypeNumber  DatasetFieldNewParamsFieldsValueType = "number"
	DatasetFieldNewParamsFieldsValueTypeString  DatasetFieldNewParamsFieldsValueType = "string"
	DatasetFieldNewParamsFieldsValueTypeJson    DatasetFieldNewParamsFieldsValueType = "json"
)

func (r DatasetFieldNewParamsFieldsValueType) IsKnown() bool {
	switch r {
	case DatasetFieldNewParamsFieldsValueTypeBoolean,
		DatasetFieldNewParamsFieldsValueTypeInteger,
		DatasetFieldNewParamsFieldsValueTypeNumber,
		DatasetFieldNewParamsFieldsValueTypeString,
		DatasetFieldNewParamsFieldsValueTypeJson:
		return true
	}
	return false
}
