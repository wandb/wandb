package provenance

import (
	"encoding/json"
	"time"

	"github.com/wandb/wandb/core/internal/provenance/platform"
)

type Manifest struct {
	Header
	Level               int                        `json:"level"`
	LocalRank           int                        `json:"local_rank"`
	NodeRank            int                        `json:"node_rank"`
	WorldSize           *int                       `json:"world_size,omitempty"`
	JobID               string                     `json:"job_id,omitempty"`
	Scheduler           string                     `json:"scheduler,omitempty"`
	Framework           string                     `json:"framework,omitempty"`
	FrameworkRevision   string                     `json:"framework_revision,omitempty"`
	ParallelCoordinates map[string]int             `json:"parallel_coordinates,omitempty"`
	SDKVersion          string                     `json:"sdk_version"`
	PrivacyPolicy       string                     `json:"privacy_policy"`
	Capabilities        map[string]Capability      `json:"capabilities"`
	Quality             Quality                    `json:"quality"`
	Finalized           bool                       `json:"finalized"`
	SamplingIntervalS   int                        `json:"sampling_interval_s"`
	ChunkIntervalS      int                        `json:"chunk_interval_s"`
	Platform            *platform.Snapshot         `json:"platform,omitempty"`
	Binding             map[string]json.RawMessage `json:"binding,omitempty"`
	Device              *Device                    `json:"device,omitempty"`
	PeakFLOPs           *PeakFLOPs                 `json:"peak_flops,omitempty"`
	Build               *Build                     `json:"build,omitempty"`
	Exit                *Exit                      `json:"exit,omitempty"`
}

type Exit struct {
	Code   int32  `json:"code"`
	Reason string `json:"reason"`
}

type Device struct {
	ID          string  `json:"id"`
	Name        string  `json:"name,omitempty"`
	MemoryBytes uint64  `json:"memory_bytes,omitempty"`
	PCIID       string  `json:"pci_id,omitempty"`
	NUMA        *uint32 `json:"numa,omitempty"`
}

type Primary struct {
	Version   int       `json:"v"`
	WriterID  string    `json:"writer_id"`
	Attempt   int       `json:"attempt"`
	StartedAt time.Time `json:"started_at"`
	Manifest  string    `json:"manifest"`
	Rollup    string    `json:"rollup"`
	Finalized bool      `json:"finalized"`
}
