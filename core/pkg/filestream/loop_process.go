package filestream

type processedChunk struct {
	fileType   ChunkTypeEnum
	fileLine   string
	Complete   *bool
	Exitcode   *int32
	Preempting bool
	Uploaded   []string
}

func (fs *fileStream) addProcess(input Update) {
	select {
	case fs.processChan <- input:

	// If the filestream dies, this prevents us from blocking forever.
	case <-fs.deadChan:
	}
}

func (fs *fileStream) loopProcess(inChan <-chan Update) {
	fs.logger.Debug("filestream: open", "path", fs.path)

	for update := range inChan {
		err := update.Chunk(fs)

		if err != nil {
			fs.logFatalAndStopWorking(err)
			return
		}
	}
}
