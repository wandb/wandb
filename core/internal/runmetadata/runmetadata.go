package runmetadata

import (
	"encoding/json"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

type RunMetadata struct {
	metadata *spb.MetadataRecord
}

func New() *RunMetadata {
	return &RunMetadata{}
}

func (rm *RunMetadata) ProcessRecord(metadata *spb.MetadataRecord) {
	if rm.metadata == nil {
		rm.metadata = &spb.MetadataRecord{}
	}
	proto.Merge(rm.metadata, metadata)
}

func (rm *RunMetadata) ToJSON() []byte {
	mo := protojson.MarshalOptions{
		Indent: "  ",
		// EmitUnpopulated: true,
	}
	jsonBytes, err := mo.Marshal(rm.metadata)
	if err != nil {
		return nil
	}
	return jsonBytes
}

func (rm *RunMetadata) ToMap() map[string]any {
	var m map[string]interface{}
	if err := json.Unmarshal(rm.ToJSON(), &m); err != nil {
		return nil
	}
	return m
}
