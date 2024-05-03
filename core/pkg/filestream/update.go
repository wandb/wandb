package filestream

// Update is unprocessed data that the filestream operates on.
type Update interface {
	// Chunk processes the update and transmits zero or more chunks.
	Chunk(*fileStream) error
}
