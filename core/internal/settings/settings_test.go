package settings_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func TestHistoryValueEncoding(t *testing.T) {
	for _, test := range []struct {
		name                       string
		json, typed                *wrapperspb.BoolValue
		wantJSON, wantTyped, valid bool
	}{
		{"default", nil, nil, true, false, true},
		{"json", wrapperspb.Bool(true), wrapperspb.Bool(false), true, false, true},
		{"typed", wrapperspb.Bool(false), wrapperspb.Bool(true), false, true, true},
		{"dual", wrapperspb.Bool(true), wrapperspb.Bool(true), true, true, true},
		{"typed with omitted json", nil, wrapperspb.Bool(true), true, true, true},
		{"disabled", wrapperspb.Bool(false), wrapperspb.Bool(false), false, false, false},
		{"disabled with omitted typed", wrapperspb.Bool(false), nil, false, false, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			s := settings.From(&spb.Settings{
				XHistoryValueEncodingJson:  test.json,
				XHistoryValueEncodingTyped: test.typed,
			})
			assert.Equal(t, test.wantJSON, s.IsHistoryValueEncodingJSON())
			assert.Equal(t, test.wantTyped, s.IsHistoryValueEncodingTyped())
			if test.valid {
				assert.NoError(t, s.ValidateHistoryValueEncoding())
			} else {
				assert.ErrorContains(t, s.ValidateHistoryValueEncoding(), "at least one")
			}
		})
	}
}
