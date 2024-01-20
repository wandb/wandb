package datatypes_test

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/wandb/wandb/core/internal/datatypes"
)

type CustomType struct{}

func TestGenerateTypeRepresentation(t *testing.T) {
	testCases := []struct {
		name     string
		input    interface{}
		expected datatypes.TypeRepresentation
	}{
		{
			name:  "Empty Map",
			input: map[string]interface{}{},
			expected: datatypes.TypeRepresentation{
				Name:   datatypes.MapTypeName,
				Params: &datatypes.MapType{Type: map[string]datatypes.TypeRepresentation{}},
			},
		},
		{
			name: "Nested Number, String, and Boolean",
			input: map[string]interface{}{
				"a": 1,
				"b": "hello",
				"c": true,
			},
			expected: datatypes.TypeRepresentation{
				Name: datatypes.MapTypeName,
				Params: &datatypes.MapType{
					Type: map[string]datatypes.TypeRepresentation{
						"a": {Name: datatypes.NumberTypeName},
						"b": {Name: datatypes.StringTypeName},
						"c": {Name: datatypes.BooleanTypeName},
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
			expected: datatypes.TypeRepresentation{
				Name: datatypes.MapTypeName,
				Params: &datatypes.MapType{
					Type: map[string]datatypes.TypeRepresentation{
						"a": {
							Name: datatypes.MapTypeName,
							Params: &datatypes.MapType{
								Type: map[string]datatypes.TypeRepresentation{
									"aa": {Name: datatypes.NumberTypeName},
								},
							},
						},
						"b": {
							Name: datatypes.ListTypeName,
							Params: &datatypes.ListType{
								ElementType: datatypes.TypeRepresentation{Name: datatypes.NumberTypeName},
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
			expected: datatypes.TypeRepresentation{
				Name: datatypes.MapTypeName,
				Params: &datatypes.MapType{
					Type: map[string]datatypes.TypeRepresentation{
						"a": {
							Name: datatypes.ListTypeName,
							Params: &datatypes.ListType{
								ElementType: datatypes.TypeRepresentation{
									Name: datatypes.ListTypeName,
									Params: &datatypes.ListType{
										ElementType: datatypes.TypeRepresentation{Name: datatypes.NumberTypeName},
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
			expected: datatypes.TypeRepresentation{
				Name: datatypes.MapTypeName,
				Params: &datatypes.MapType{
					Type: map[string]datatypes.TypeRepresentation{
						"a": {Name: datatypes.UnknownTypeName},
					},
				},
			},
		},
		// TODO: this test case sometimes fails because the order of the type union is not deterministic
		//  however, it should not matter, so we should fix this test case
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
			expected: datatypes.TypeRepresentation{
				Name: datatypes.MapTypeName,
				Params: &datatypes.MapType{
					Type: map[string]datatypes.TypeRepresentation{
						"deep": {
							Name: datatypes.MapTypeName,
							Params: &datatypes.MapType{
								Type: map[string]datatypes.TypeRepresentation{
									"numbers": {
										Name: datatypes.ListTypeName,
										Params: &datatypes.ListType{
											ElementType: datatypes.TypeRepresentation{Name: datatypes.NumberTypeName},
											Length:      3,
										},
									},
									"mixed": {
										Name: datatypes.ListTypeName,
										Params: &datatypes.ListType{
											ElementType: datatypes.TypeRepresentation{
												Name: datatypes.UnionTypeName,
												Params: &datatypes.UnionType{
													AllowedTypes: []datatypes.TypeRepresentation{
														{
															Name: datatypes.ListTypeName,
															Params: &datatypes.ListType{
																ElementType: datatypes.TypeRepresentation{Name: datatypes.NumberTypeName},
																Length:      3,
															},
														},
														{
															Name: datatypes.MapTypeName,
															Params: &datatypes.MapType{
																Type: map[string]datatypes.TypeRepresentation{
																	"a": {Name: datatypes.NumberTypeName},
																	"b": {Name: datatypes.StringTypeName},
																},
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
			result := datatypes.ResolveTypes(tc.input)
			if !reflect.DeepEqual(result, tc.expected) {
				jsonExpected, _ := json.MarshalIndent(tc.expected, "", "  ")
				jsonResult, _ := json.MarshalIndent(result, "", "  ")
				t.Errorf("\nExpected: %v\nActual:   %v", string(jsonExpected), string(jsonResult))
			}
		})
	}
}
