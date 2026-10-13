package provenance

import (
	"strings"
	"time"
)

type Header struct {
	Version     int       `json:"v"`
	Kind        string    `json:"kind"`
	WriterID    string    `json:"writer_id"`
	CollectedAt time.Time `json:"collected_at"`
	RuntimeS    *float64  `json:"runtime_s,omitempty"`
	Attempt     int       `json:"attempt"`
	Rank        int       `json:"rank"`
	Source      string    `json:"source"`
}

type Capability struct {
	Status string `json:"status"`
	Reason string `json:"reason,omitempty"`
}

type Quality struct {
	RejectedRecords      int64  `json:"rejected_records"`
	DroppedRecords       int64  `json:"dropped_records"`
	QueueDepth           int    `json:"queue_depth"`
	PeakMemoryBytes      int64  `json:"peak_memory_bytes"`
	SerializedBytes      int64  `json:"serialized_bytes"`
	CollectorCPUNS       *int64 `json:"collector_cpu_ns,omitempty"`
	CompressionNS        int64  `json:"compression_ns"`
	UploadRegistrationNS int64  `json:"upload_registration_ns"`
	Gaps                 int64  `json:"gaps"`
	BackoffTransitions   int64  `json:"backoff_transitions"`
}

type StartConfig struct {
	WriterID     string
	RunID        string
	Level        int
	Rank         int
	LocalRank    int
	NodeRank     int
	Attempt      int
	Primary      bool
	IdentityJSON []byte
}

type Record struct {
	Kind        string
	PayloadJSON []byte
	MonotonicNS int64
	WallTimeNS  int64
}

// valid reports whether the identity fields are in range and WriterID is a safe path component.
func (c StartConfig) valid() bool {
	levelOK := c.Level >= 0 && c.Level <= 1
	ranksOK := c.Rank >= 0 && c.LocalRank >= 0 && c.NodeRank >= 0 && c.Attempt >= 0
	writerOK := c.WriterID != "" && len(c.WriterID) <= 128
	return levelOK && ranksOK && writerOK && !strings.ContainsAny(c.WriterID, "/\\.")
}
