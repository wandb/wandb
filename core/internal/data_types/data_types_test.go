package data_types_test

import (
	"reflect"
	"testing"

	"github.com/wandb/wandb/core/internal/data_types"
)

func TestGenerateTypeRepresentation(t *testing.T) {
	testCases := []struct {
		name     string
		input    interface{}
		expected data_types.TypeRepresentation
	}{
		{
			name:  "Empty Map",
			input: map[string]interface{}{},
			expected: data_types.TypeRepresentation{
				WbType: "typedDict",
				Params: map[string]interface{}{
					"type_map": map[string]interface{}{},
				},
			},
		},
		{
			name: "Nested Number, String, and Boolean",
			input: map[string]interface{}{
				"a":  1,
				"b":  "hello",
				"c":  true,
				"_o": 42,
			},
			expected: data_types.TypeRepresentation{
				WbType: "typedDict",
				Params: map[string]interface{}{
					"type_map": map[string]interface{}{
						"a": data_types.TypeRepresentation{WbType: "number"},
						"b": data_types.TypeRepresentation{WbType: "string"},
						"c": data_types.TypeRepresentation{WbType: "boolean"},
					},
				},
			},
		},
		{
			name: "Nested Map and List",
			input: map[string]interface{}{
				"a": map[string]interface{}{
					"aa": 1,
				},
				"b": []interface{}{1, 2, 3},
			},
			expected: data_types.TypeRepresentation{
				WbType: "typedDict",
				Params: map[string]interface{}{
					"type_map": map[string]interface{}{
						"a": data_types.TypeRepresentation{
							WbType: "typedDict",
							Params: map[string]interface{}{
								"type_map": map[string]interface{}{
									"aa": data_types.TypeRepresentation{WbType: "number"},
								},
							},
						},
						"b": data_types.TypeRepresentation{
							WbType: "list",
							Params: map[string]interface{}{
								"element_type": data_types.TypeRepresentation{WbType: "number"},
								"length":       3,
							},
						},
					},
				},
			},
		},
		{
			name: "List of Lists",
			input: map[string]interface{}{
				"a": []interface{}{
					[]interface{}{1, 2},
					[]interface{}{3, 4},
				},
			},
			expected: data_types.TypeRepresentation{
				WbType: "typedDict",
				Params: map[string]interface{}{
					"type_map": map[string]interface{}{
						"a": data_types.TypeRepresentation{
							WbType: "list",
							Params: map[string]interface{}{
								"element_type": data_types.TypeRepresentation{
									WbType: "list",
									Params: map[string]interface{}{
										"element_type": data_types.TypeRepresentation{WbType: "number"},
										"length":       2,
									},
								},
								"length": 2,
							},
						},
					},
				},
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result := data_types.GenerateTypeRepresentation(tc.input)
			if !reflect.DeepEqual(result, tc.expected) {
				t.Errorf("\nExpected: %v\nActual:   %v", tc.expected, result)
			}
		})
	}
}
