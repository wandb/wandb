package data_types

type TypeRepresentation struct {
	WbType string                 `json:"wb_type"`
	Params map[string]interface{} `json:"params,omitempty"`
}

func GenerateTypeRepresentation(data interface{}) TypeRepresentation {
	return generateTypeRepresentation(data)
}

func generateTypeRepresentation(data interface{}) TypeRepresentation {
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
		elemType := TypeRepresentation{}
		if len(v) > 0 {
			elemType = generateTypeRepresentation(v[0])
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
	return TypeRepresentation{}
}
