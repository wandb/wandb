package filestream

// TransmitChunk is data to be sent to the filestream endpoint.
//
// A TransmitChunk is also a CollectorStateUpdate via updating
// the buffered data.
type TransmitChunk struct {
	HistoryLines    []string
	SummaryLines    []string
	EventsLines     []string
	ConsoleLogLines []string

	UploadedFiles []string

	HasPreempting bool
	Preempting    bool
}

func (c *TransmitChunk) Apply(state *CollectorState) {
	state.Buffer.HistoryLines =
		append(state.Buffer.HistoryLines, c.HistoryLines...)
	state.Buffer.SummaryLines =
		append(state.Buffer.SummaryLines, c.SummaryLines...)
	state.Buffer.EventsLines =
		append(state.Buffer.EventsLines, c.EventsLines...)
	state.Buffer.ConsoleLogLines =
		append(state.Buffer.ConsoleLogLines, c.ConsoleLogLines...)

	state.Buffer.UploadedFiles =
		append(state.Buffer.UploadedFiles, c.UploadedFiles...)

	if c.HasPreempting {
		state.Buffer.HasPreempting = true
		state.Buffer.Preempting = c.Preempting
	}
}

// Write writes the buffered data to the filestream request.
//
// Returns whether any data was written.
func (c *TransmitChunk) Write(
	data *FsTransmitData,
	offsets FileStreamOffsetMap,
) bool {
	files := make(map[string]fsTransmitFileData)
	addLines := func(chunkType ChunkTypeEnum, lines []string) {
		if len(lines) > 0 {
			files[chunkFilename[chunkType]] = fsTransmitFileData{
				Offset:  offsets[chunkType],
				Content: lines,
			}
		}
	}
	addLines(HistoryChunk, c.HistoryLines)
	addLines(SummaryChunk, c.SummaryLines)
	addLines(EventsChunk, c.EventsLines)
	addLines(OutputChunk, c.ConsoleLogLines)

	hasData := false

	if len(files) > 0 {
		data.Files = files
		hasData = true
	}

	if len(c.UploadedFiles) > 0 {
		data.Uploaded = c.UploadedFiles
		hasData = true
	}

	if c.HasPreempting {
		data.Preempting = c.Preempting
		hasData = true
	}

	return hasData
}
