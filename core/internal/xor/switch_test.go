package xor_test

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/xor"
)

var (
	errGood = errors.New("good")
	errBad  = errors.New("bad")
)

func TestSwitch_OneMatch(t *testing.T) {
	ran, err := xor.Switch().
		Case(false, func() error { return errBad }).
		Case(true, func() error { return errGood }).
		Case(false, func() error { return errBad }).
		RunExactlyOne()

	assert.True(t, ran)
	assert.ErrorIs(t, err, errGood)
}

func TestSwitch_NoMatch(t *testing.T) {
	ran, err := xor.Switch().
		Case(false, func() error { return errBad }).
		Case(false, func() error { return errBad }).
		RunExactlyOne()

	assert.False(t, ran)
	assert.ErrorIs(t, err, xor.ErrNoMatch)
}

func TestSwitch_NoCases(t *testing.T) {
	ran, err := xor.Switch().RunExactlyOne()

	assert.False(t, ran)
	assert.ErrorIs(t, err, xor.ErrNoMatch)
}

func TestSwitch_MoreThanOneMatch(t *testing.T) {
	ran, err := xor.Switch().
		Case(true, func() error { return errBad }).
		Case(false, func() error { return errBad }).
		Case(true, func() error { return errBad }).
		RunExactlyOne()

	assert.False(t, ran)
	assert.ErrorIs(t, err, xor.ErrMoreThanOneMatch)
}
