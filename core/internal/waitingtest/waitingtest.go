// Package waitingtest defines fakes for package `waiting`.
package waitingtest

func completedDelay() <-chan struct{} {
	ch := make(chan struct{}, 1)
	close(ch)
	return ch
}
