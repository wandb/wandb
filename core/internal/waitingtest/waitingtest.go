// Package waitingtest defines fakes for package `waiting`.
package waitingtest

func completedDelay() <-chan struct{} {
	ch := make(chan struct{})
	close(ch)
	return ch
}
