// sub-package for gowandb session options
package session

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb"
)

func WithCoreBinary(coreBinary []byte) gowandb.SessionOption {
	return func(s *gowandb.Session) {
		s.CoreBinary = coreBinary
	}
}

func WithCoreAddress(address string) gowandb.SessionOption {
	return func(s *gowandb.Session) {
		s.Address = address
	}
}

func WithSettings(settings *gowandb.SettingsWrap) gowandb.SessionOption {
	return func(s *gowandb.Session) {
		s.Settings = settings
	}
}
