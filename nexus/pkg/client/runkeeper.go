package client

type RunKeeper struct {
	runs map[int]*Run
}

func NewRunKeeper() *RunKeeper {
	return &RunKeeper{
		runs: make(map[int]*Run),
	}
}

func (k *RunKeeper) Get(num int) *Run {
	return k.runs[num]
}

func (k *RunKeeper) Add(run *Run) int {
	num := 42
	k.runs[num] = run
	return num
}
