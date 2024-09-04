package artifacts

import (
	"encoding/json"
	"fmt"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	clientId         = "clientID-1"
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
	assert.Nil(t, err)
	baseArtifact := &spb.ArtifactRecord{
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
	err = builder.AddData("obj.object.json", weaveObjectData)
	assert.Nil(t, err)
	err = builder.AddData("obj.type.json", weaveTypeData)
	assert.Nil(t, err)

	file, err := os.CreateTemp("", "test-name.txt")
	assert.Nil(t, err)
	_, err = file.WriteString("wandb")
	assert.Nil(t, err)
	err = file.Sync()
	assert.Nil(t, err)
	file.Close()
	err = builder.AddFile(file.Name(), "test-name.txt")
	assert.Nil(t, err)

	art := builder.GetArtifact()
	assert.Equal(t, art.Digest, "2f122f2bff8133c0d5806d9bac1b958c")
	fmt.Printf("ART %+v\n", art)
}
