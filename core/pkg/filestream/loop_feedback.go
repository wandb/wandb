package filestream

func (fs *FileStream) addFeedback(reply map[string]interface{}) {
	fs.feedbackChan <- reply
}

func (fs *FileStream) loopFeedback(inChan <-chan map[string]interface{}) {
	for range inChan {
	}
}
