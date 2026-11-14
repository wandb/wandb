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

// DatasetVersionFieldService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetVersionFieldService] method instead.
type DatasetVersionFieldService struct {
	Options []option.RequestOption
}

// NewDatasetVersionFieldService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewDatasetVersionFieldService(opts ...option.RequestOption) (r *DatasetVersionFieldService) {
	r = &DatasetVersionFieldService{}
	r.Options = opts
	return
}

// Returns the input and output field names and types recorded in this dataset
// version.
func (r *DatasetVersionFieldService) List(
	ctx context.Context,
	datasetVersionID string,
	query DatasetVersionFieldListParams,
	opts ...option.RequestOption,
) (res *DatasetVersionFieldListResponse, err error) {
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
	if datasetVersionID == "" {
		err = errors.New("missing required dataset_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/dataset-versions/%s/fields",
		query.Namespace,
		query.ScopeID,
		datasetVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type DatasetVersionFieldListResponse struct {
	Fields []DatasetVersionFieldListResponseField `json:"fields" api:"required"`
	JSON   datasetVersionFieldListResponseJSON    `json:"-"`
}

// datasetVersionFieldListResponseJSON contains the JSON metadata for the struct
// [DatasetVersionFieldListResponse]
type datasetVersionFieldListResponseJSON struct {
	Fields      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetVersionFieldListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionFieldListResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionFieldListResponseField struct {
	DatasetFieldID int64                                          `json:"dataset_field_id" api:"required"`
	Name           string                                         `json:"name"             api:"required"`
	Source         DatasetVersionFieldListResponseFieldsSource    `json:"source"           api:"required"`
	ValueType      DatasetVersionFieldListResponseFieldsValueType `json:"value_type"       api:"required"`
	JSON           datasetVersionFieldListResponseFieldJSON       `json:"-"`
}

// datasetVersionFieldListResponseFieldJSON contains the JSON metadata for the
// struct [DatasetVersionFieldListResponseField]
type datasetVersionFieldListResponseFieldJSON struct {
	DatasetFieldID apijson.Field
	Name           apijson.Field
	Source         apijson.Field
	ValueType      apijson.Field
	raw            string
	ExtraFields    map[string]apijson.Field
}

func (r *DatasetVersionFieldListResponseField) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionFieldListResponseFieldJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionFieldListResponseFieldsSource string

const (
	DatasetVersionFieldListResponseFieldsSourceInput  DatasetVersionFieldListResponseFieldsSource = "input"
	DatasetVersionFieldListResponseFieldsSourceOutput DatasetVersionFieldListResponseFieldsSource = "output"
)

func (r DatasetVersionFieldListResponseFieldsSource) IsKnown() bool {
	switch r {
	case DatasetVersionFieldListResponseFieldsSourceInput, DatasetVersionFieldListResponseFieldsSourceOutput:
		return true
	}
	return false
}

type DatasetVersionFieldListResponseFieldsValueType string

const (
	DatasetVersionFieldListResponseFieldsValueTypeBoolean DatasetVersionFieldListResponseFieldsValueType = "boolean"
	DatasetVersionFieldListResponseFieldsValueTypeInteger DatasetVersionFieldListResponseFieldsValueType = "integer"
	DatasetVersionFieldListResponseFieldsValueTypeNumber  DatasetVersionFieldListResponseFieldsValueType = "number"
	DatasetVersionFieldListResponseFieldsValueTypeString  DatasetVersionFieldListResponseFieldsValueType = "string"
	DatasetVersionFieldListResponseFieldsValueTypeJson    DatasetVersionFieldListResponseFieldsValueType = "json"
)

func (r DatasetVersionFieldListResponseFieldsValueType) IsKnown() bool {
	switch r {
	case DatasetVersionFieldListResponseFieldsValueTypeBoolean,
		DatasetVersionFieldListResponseFieldsValueTypeInteger,
		DatasetVersionFieldListResponseFieldsValueTypeNumber,
		DatasetVersionFieldListResponseFieldsValueTypeString,
		DatasetVersionFieldListResponseFieldsValueTypeJson:
		return true
	}
	return false
}

type DatasetVersionFieldListParams struct {
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
