package runmetadata

import (
	"encoding/json"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

// RunMetadata tracks the metadata for a run's writer.
type RunMetadata struct {
	// Unique ID of a writer to the run.
	clientID string

	metadata *spb.MetadataRecord
}

func New(clientID string) *RunMetadata {
	return &RunMetadata{
		clientID: clientID,
		metadata: &spb.MetadataRecord{},
	}
}

func (rm *RunMetadata) ProcessRecord(metadata *spb.MetadataRecord) {
	proto.Merge(rm.metadata, metadata)
}

func (rm *RunMetadata) ToJSON() ([]byte, error) {
	mo := protojson.MarshalOptions{
		Indent: "  ",
		// EmitUnpopulated: true,
	}
	jsonBytes, err := mo.Marshal(rm.metadata.GetMetadata())
	if err != nil {
		return nil, err
	}
	return jsonBytes, nil
}

// ToRunConfigData returns the data to store in the "d" (metadata) field of
// the run config.
//
// Metadata in the config is stored per unique client ID to support
// multi-writer use cases (e.g. shared mode or resume).
func (rm *RunMetadata) ToRunConfigData() map[string]any {
	var m map[string]any
	metadataJSON, err := rm.ToJSON()
	if err != nil {
		return nil
	}
	if err := json.Unmarshal(metadataJSON, &m); err != nil {
		return nil
	}

	return map[string]any{rm.clientID: m}
}
