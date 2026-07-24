package encodingbench

import (
	"encoding/json"
	"fmt"
)

const historyFileName = "wandb-history.jsonl"

func marshalJSONEnvelope(content []string) ([]byte, error) {
	return marshalSortedJSON(map[string]any{
		"files": map[string]any{
			historyFileName: map[string]any{
				"offset":  0,
				"content": content,
			},
		},
	})
}

func unmarshalJSONEnvelope(data []byte) ([]string, error) {
	var request struct {
		Files map[string]struct {
			Offset  int      `json:"offset"`
			Content []string `json:"content"`
		} `json:"files"`
	}
	if err := json.Unmarshal(data, &request); err != nil {
		return nil, fmt.Errorf("unmarshal JSON envelope: %w", err)
	}
	chunk, ok := request.Files[historyFileName]
	if !ok {
		return nil, fmt.Errorf("JSON envelope is missing %q", historyFileName)
	}
	if chunk.Offset != 0 {
		return nil, fmt.Errorf("unexpected history offset %d", chunk.Offset)
	}
	return chunk.Content, nil
}
