package data_types

type TypeRepresentation struct {
	WbType string                 `json:"wb_type"`
	Params map[string]interface{} `json:"params,omitempty"`
}

func GenerateTypeRepresentation(data interface{}) TypeRepresentation {
	return generateTypeRepresentation(data)
}

func generateTypeRepresentation(data interface{}, invalid ...bool) TypeRepresentation {
	encounteredInvalid := len(invalid) > 0 && invalid[0]

	switch v := data.(type) {
	case map[string]interface{}:
		typedDict := TypeRepresentation{
			WbType: "typedDict",
			Params: map[string]interface{}{
				"type_map": make(map[string]interface{}),
			},
		}
		for key, value := range v {
			if len(key) == 0 || key[0] != '_' {
				typedDict.Params["type_map"].(map[string]interface{})[key] = generateTypeRepresentation(value)
			}
		}
		return typedDict

	case []interface{}:
		if len(v) == 0 {
			return TypeRepresentation{
				WbType: "list",
				Params: map[string]interface{}{
					"element_type": TypeRepresentation{WbType: "none"},
					"length":       0,
				},
			}
		}
		elemType := generateTypeRepresentation(v[0])
		isInvalid := elemType.WbType == "invalid"
		for _, elem := range v[1:] {
			elemRep := generateTypeRepresentation(elem, isInvalid)
			if elemRep.WbType != elemType.WbType {
				elemType = TypeRepresentation{
					WbType: "union",
					Params: map[string]interface{}{
						"allowed_types": []TypeRepresentation{elemType, elemRep},
					},
				}
				break
			}
		}
		if encounteredInvalid {
			elemType.WbType = "invalid"
		}
		return TypeRepresentation{
			WbType: "list",
			Params: map[string]interface{}{
				"element_type": elemType,
				"length":       len(v),
			},
		}

	case int, float64:
		return TypeRepresentation{
			WbType: "number",
		}

	case string:
		return TypeRepresentation{
			WbType: "string",
		}

	case bool:
		return TypeRepresentation{
			WbType: "boolean",
		}

	case nil:
		return TypeRepresentation{
			WbType: "none",
		}
	}

	if encounteredInvalid {
		return TypeRepresentation{
			WbType: "unknown",
		}
	}
	return TypeRepresentation{
		WbType: "invalid",
	}
}
