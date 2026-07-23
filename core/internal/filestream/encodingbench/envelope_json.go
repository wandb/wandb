package encodingbench

import (
	"encoding/json"
	"fmt"
)

const historyFileName = "wandb-history.jsonl"

// These types intentionally mirror filestream.FileStreamRequestJSON and its
// unexported offsetAndContent value type.
type fileStreamRequestJSON struct {
	Files map[string]offsetAndContentJSON `json:"files,omitempty"`
}

type offsetAndContentJSON struct {
	Offset  int      `json:"offset"`
	Content []string `json:"content"`
}

func marshalJSONEnvelope(content []string) ([]byte, error) {
	return json.Marshal(&fileStreamRequestJSON{Files: map[string]offsetAndContentJSON{
		historyFileName: {Offset: 0, Content: content},
	}})
}

func unmarshalJSONEnvelope(data []byte) ([]string, error) {
	var request fileStreamRequestJSON
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
