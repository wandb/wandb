// sub-package for gowandb session options
package sessionopts

import (
	"github.com/wandb/wandb/experimental/client-go/gowandb/settings"
)

type SessionParams struct {
	CoreBinary []byte
	Address    string
	Settings   *settings.SettingsWrap
}

type SessionOption func(*SessionParams)

func WithCoreBinary(coreBinary []byte) SessionOption {
	return func(s *SessionParams) {
		s.CoreBinary = coreBinary
	}
}

func WithCoreAddress(address string) SessionOption {
	return func(s *SessionParams) {
		s.Address = address
	}
}

func WithSettings(baseSettings *settings.SettingsWrap) SessionOption {
	return func(s *SessionParams) {
		s.Settings = baseSettings
	}
}
