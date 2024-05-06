package filestream

func (fs *fileStream) addFeedback(reply map[string]interface{}) {
	fs.feedbackChan <- reply
}

func (fs *fileStream) loopFeedback(inChan <-chan map[string]interface{}) {
	for range inChan {
	}
}
