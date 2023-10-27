package artifacts

import (
	"fmt"
	"testing"
	"encoding/json"

	// "github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/nexus/pkg/service"
)

const (
	clientId = "clientID-1"
	sequenceClientId = "sequenceClientID-1"
)

func TestArtifactBuilder(t *testing.T) {
	weaveObjectData := map[string]interface{}{
		"_type":        "stream_table",
		"table_name":   "tableName",
		"project_name": "project",
		"entity_name":  "entity",
	}
	weaveTypeData := map[string]interface{}{
		"type": "stream_table",
		"_base_type": map[string]interface{}{
			"type": "Object",
		},
		"_is_object":   true,
		"table_name":   "string",
		"project_name": "string",
		"entity_name":  "string",
	}
	metadata := map[string]interface{}{
		"_weave_meta": map[string]interface{}{
			"is_panel":     false,
			"is_weave_obj": true,
			"type_name":    "stream_table",
		},
	}
	metadataJson, err := json.Marshal(metadata)
	if err != nil {
		// s.logger.CaptureFatalAndPanic("sender: createStreamTableArtifact: bad weave meta", err)
	}
	baseArtifact := &service.ArtifactRecord{
		Manifest: &service.ArtifactManifest{
			Version:       1,
			StoragePolicy: "wandb-storage-policy-v1",
			StoragePolicyConfig: []*service.StoragePolicyConfigItem{{
				Key:       "storageLayout",
				ValueJson: "\"V2\"",
			}},
		},
		Entity:           "entity",
		Project:          "project",
		RunId:            "runid",
		Name:             "tableName",
		Metadata:         string(metadataJson),
		Type:             "stream_table",
		Aliases:          []string{"latest"},
		Finalize:         true,
		ClientId:         clientId,
		SequenceClientId: sequenceClientId,
	}
	builder := NewArtifactBuilder(baseArtifact)
	if err := builder.AddData("obj.object.json", weaveObjectData); err != nil {
		// s.logger.CaptureFatalAndPanic("sender: createStreamTableArtifact: bad weave object", err)
	}
	if err := builder.AddData("obj.type.json", weaveTypeData); err != nil {
		// s.logger.CaptureFatalAndPanic("sender: createStreamTableArtifact: bad weave type", err)
	}
	art := builder.GetArtifact()
	fmt.Printf("ART %+v\n", art)
}
