package runenvironment

import (
	"encoding/json"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

// RunEnvironment stores the information about the system, hardware, software,
// and execution parameters for a run's writer.
type RunEnvironment struct {
	// mu protects the environment field
	mu sync.Mutex

	// Unique ID of the writer to the run.
	writerID string

	environment *spb.EnvironmentRecord
}

func New(writerID string) *RunEnvironment {
	return &RunEnvironment{
		writerID:    writerID,
		environment: &spb.EnvironmentRecord{},
	}
}

func (re *RunEnvironment) ProcessRecord(environment *spb.EnvironmentRecord) {
	re.mu.Lock()
	defer re.mu.Unlock()

	proto.Merge(re.environment, environment)
}

func (re *RunEnvironment) ToJSON() ([]byte, error) {
	re.mu.Lock()
	defer re.mu.Unlock()

	mo := protojson.MarshalOptions{Indent: "  "}
	jsonBytes, err := mo.Marshal(re.environment)
	if err != nil {
		return nil, err
	}
	return jsonBytes, nil
}

// ToRunConfigData returns the data to store in the "e" field of the run config.
//
// Environment info in the config is stored per unique writer ID to support
// multi-writer use cases (e.g. shared mode or resume).
func (re *RunEnvironment) ToRunConfigData() map[string]any {
	var m map[string]any
	// TODO: avoid converting to and parsing JSON
	environmentJSON, err := re.ToJSON()
	if err != nil {
		return nil
	}
	if err := json.Unmarshal(environmentJSON, &m); err != nil {
		return nil
	}

	if len(m) == 0 {
		return nil
	}

	return map[string]any{re.writerID: m}
}
