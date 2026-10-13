package provenance

type Rollup struct {
	Header
	Quality      Quality          `json:"quality"`
	Records      map[string]int64 `json:"records"`
	LastSequence int              `json:"last_sequence"`
	Finalized    bool             `json:"finalized"`
}
