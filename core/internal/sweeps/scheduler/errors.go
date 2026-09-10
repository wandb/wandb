package scheduler

import "errors"

var ErrSweepNotFound = errors.New("scheduler: sweep not found")
var ErrUnsupportedServer = errors.New(
	"scheduler: this W&B server does not support the local sweep scheduler")
