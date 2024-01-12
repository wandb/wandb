package data_types_test

import (
	"reflect"
	"testing"

	"github.com/wandb/wandb/core/internal/data_types"
)

type CustomType struct{}

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
				Type:   data_types.MapTypeName,
				Params: &data_types.MapType{Type: map[string]data_types.TypeRepresentation{}},
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
				Type: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {Type: data_types.NumberTypeName},
						"b": {Type: data_types.StringTypeName},
						"c": {Type: data_types.BooleanTypeName},
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
				Type: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {
							Type: data_types.MapTypeName,
							Params: &data_types.MapType{
								Type: map[string]data_types.TypeRepresentation{
									"aa": {Type: data_types.NumberTypeName},
								},
							},
						},
						"b": {
							Type: data_types.ListTypeName,
							Params: &data_types.ListType{
								ElementType: data_types.TypeRepresentation{Type: data_types.NumberTypeName},
								Length:      3,
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
				Type: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {
							Type: data_types.ListTypeName,
							Params: &data_types.ListType{
								ElementType: data_types.TypeRepresentation{
									Type: data_types.ListTypeName,
									Params: &data_types.ListType{
										ElementType: data_types.TypeRepresentation{Type: data_types.NumberTypeName},
										Length:      2,
									},
								},
								Length: 2,
							},
						},
					},
				},
			},
		},
		{
			name: "Unknown Type",
			input: map[string]interface{}{
				"a": CustomType{},
			},
			expected: data_types.TypeRepresentation{
				Type: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {Type: data_types.InvalidTypeName},
					},
				},
			},
		},
		{
			name: "Complex Nested Map and List",
			input: map[string]interface{}{
				"deep": map[string]interface{}{
					"numbers": []interface{}{1, 2, 3},
					"mixed": []interface{}{
						map[string]interface{}{
							"a": 1,
							"b": "text",
						},
						[]interface{}{4, 5, 6},
					},
				},
			},
			expected: data_types.TypeRepresentation{
				Type: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"deep": {
							Type: data_types.MapTypeName,
							Params: &data_types.MapType{
								Type: map[string]data_types.TypeRepresentation{
									"numbers": {
										Type: data_types.ListTypeName,
										Params: &data_types.ListType{
											ElementType: data_types.TypeRepresentation{Type: data_types.NumberTypeName},
											Length:      3,
										},
									},
									"mixed": {
										Type: data_types.ListTypeName,
										Params: &data_types.ListType{
											ElementType: data_types.TypeRepresentation{
												Type: data_types.UnionTypeName,
												Params: &data_types.UnionType{
													AllowedTypes: []data_types.TypeRepresentation{
														{
															Type: data_types.MapTypeName,
															Params: &data_types.MapType{
																Type: map[string]data_types.TypeRepresentation{
																	"a": {Type: data_types.NumberTypeName},
																	"b": {Type: data_types.StringTypeName},
																},
															},
														},
														{
															Type: data_types.ListTypeName,
															Params: &data_types.ListType{
																ElementType: data_types.TypeRepresentation{Type: data_types.NumberTypeName},
																Length:      3,
															},
														},
													},
												},
											},
											Length: 2,
										},
									},
								},
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
