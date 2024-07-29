package version

import "strings"

const Version = "Version = "0.17.6.dev1""

const MinServerVersion = "0.40.0"

var Environment string

func init() {
	if strings.Contains(Version, "dev") {
		Environment = "development"
	} else {
		Environment = "production"
	}
}
