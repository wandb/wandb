package filestream

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
		err := update.Apply(UpdateContext{
			ModifyRequest: fs.addTransmit,

			Settings: fs.settings,
			ClientID: fs.clientId,

			Logger:  fs.logger,
			Printer: fs.printer,
		})

		if err != nil {
			fs.logFatalAndStopWorking(err)
			return
		}
	}
}
