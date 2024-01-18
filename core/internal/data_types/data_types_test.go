package data_types_test

import (
	"encoding/json"
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
				Name:   data_types.MapTypeName,
				Params: &data_types.MapType{Type: map[string]data_types.TypeRepresentation{}},
			},
		},
		{
			name: "Nested Number, String, and Boolean",
			input: map[string]interface{}{
				"a": 1,
				"b": "hello",
				"c": true,
			},
			expected: data_types.TypeRepresentation{
				Name: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {Name: data_types.NumberTypeName},
						"b": {Name: data_types.StringTypeName},
						"c": {Name: data_types.BooleanTypeName},
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
				Name: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {
							Name: data_types.MapTypeName,
							Params: &data_types.MapType{
								Type: map[string]data_types.TypeRepresentation{
									"aa": {Name: data_types.NumberTypeName},
								},
							},
						},
						"b": {
							Name: data_types.ListTypeName,
							Params: &data_types.ListType{
								ElementType: data_types.TypeRepresentation{Name: data_types.NumberTypeName},
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
				Name: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {
							Name: data_types.ListTypeName,
							Params: &data_types.ListType{
								ElementType: data_types.TypeRepresentation{
									Name: data_types.ListTypeName,
									Params: &data_types.ListType{
										ElementType: data_types.TypeRepresentation{Name: data_types.NumberTypeName},
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
				Name: data_types.MapTypeName,
				Params: &data_types.MapType{
					Type: map[string]data_types.TypeRepresentation{
						"a": {Name: data_types.UnknownTypeName},
					},
				},
			},
		},
		// TODO: this test case sometimes fails because the order of the type union is not deterministic
		//  however, it should not matter, so we should fix this test case
		// {
		// 	name: "Complex Nested Map and List",
		// 	input: map[string]interface{}{
		// 		"deep": map[string]interface{}{
		// 			"numbers": []interface{}{1, 2, 3},
		// 			"mixed": []interface{}{
		// 				map[string]interface{}{
		// 					"a": 1,
		// 					"b": "text",
		// 				},
		// 				[]interface{}{4, 5, 6},
		// 			},
		// 		},
		// 	},
		// 	expected: data_types.TypeRepresentation{
		// 		Name: data_types.MapTypeName,
		// 		Params: &data_types.MapType{
		// 			Type: map[string]data_types.TypeRepresentation{
		// 				"deep": {
		// 					Name: data_types.MapTypeName,
		// 					Params: &data_types.MapType{
		// 						Type: map[string]data_types.TypeRepresentation{
		// 							"numbers": {
		// 								Name: data_types.ListTypeName,
		// 								Params: &data_types.ListType{
		// 									ElementType: data_types.TypeRepresentation{Name: data_types.NumberTypeName},
		// 									Length:      3,
		// 								},
		// 							},
		// 							"mixed": {
		// 								Name: data_types.ListTypeName,
		// 								Params: &data_types.ListType{
		// 									ElementType: data_types.TypeRepresentation{
		// 										Name: data_types.UnionTypeName,
		// 										Params: &data_types.UnionType{
		// 											AllowedTypes: []data_types.TypeRepresentation{
		// 												{
		// 													Name: data_types.MapTypeName,
		// 													Params: &data_types.MapType{
		// 														Type: map[string]data_types.TypeRepresentation{
		// 															"a": {Name: data_types.NumberTypeName},
		// 															"b": {Name: data_types.StringTypeName},
		// 														},
		// 													},
		// 												},
		// 												{
		// 													Name: data_types.ListTypeName,
		// 													Params: &data_types.ListType{
		// 														ElementType: data_types.TypeRepresentation{Name: data_types.NumberTypeName},
		// 														Length:      3,
		// 													},
		// 												},
		// 											},
		// 										},
		// 									},
		// 									Length: 2,
		// 								},
		// 							},
		// 						},
		// 					},
		// 				},
		// 			},
		// 		},
		// 	},
		// },
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result := data_types.ResolveTypes(tc.input)
			if !reflect.DeepEqual(result, tc.expected) {
				jsonExpected, _ := json.MarshalIndent(tc.expected, "", "  ")
				jsonResult, _ := json.MarshalIndent(result, "", "  ")
				t.Errorf("\nExpected: %v\nActual:   %v", string(jsonExpected), string(jsonResult))
			}
		})
	}
}
