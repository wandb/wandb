package filestream

// TransmitChunk is data to be sent to the filestream endpoint.
type TransmitChunk struct {
	HistoryLineNum int
	HistoryLines   []string

	EventsLineNum int
	EventsLines   []string

	ConsoleLogLineNum int
	ConsoleLogLines   []string

	SummaryLineNum int
	LatestSummary  string

	UploadedFiles []string

	HasPreempting bool
	Preempting    bool
}

// FlushInto writes the buffered data to the filestream request and resets
// the chunk.
//
// Returns whether any data was written.
func (c *TransmitChunk) FlushInto(data *FsTransmitData) bool {
	files := make(map[string]FsTransmitFileData)
	addLines := func(chunkType ChunkTypeEnum, lineNum int, lines []string) {
		if len(lines) > 0 {
			files[chunkFilename[chunkType]] = FsTransmitFileData{
				Offset:  lineNum,
				Content: lines,
			}
		}
	}
	addLines(HistoryChunk, c.HistoryLineNum, c.HistoryLines)
	c.HistoryLineNum += len(c.HistoryLines)

	addLines(EventsChunk, c.EventsLineNum, c.EventsLines)
	c.EventsLineNum += len(c.EventsLines)

	addLines(OutputChunk, c.ConsoleLogLineNum, c.ConsoleLogLines)
	c.ConsoleLogLineNum += len(c.ConsoleLogLines)

	if c.LatestSummary != "" {
		// We always overwrite the same line in the summary file.
		//
		// However, some versions of the SDK appended to the summary file
		// rather than overwriting the one line, and the backend seems to read
		// the last line in that file. If a user tries to resume such a run,
		// we need to correctly update the final line in the summary file for
		// it to be reflected in the UI.
		addLines(SummaryChunk, c.SummaryLineNum, []string{c.LatestSummary})
	}

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
