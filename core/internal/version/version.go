package version

import (
	"cmp"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

const Version = "0.30.1.dev1"

const MinServerVersion = "0.70.0"

var Environment string

func init() {
	if strings.Contains(Version, "dev") {
		Environment = "development"
	} else {
		Environment = "production"
	}
}

// Compare compares two SDK versions.
//
// It returns a negative integer if the first is less than the second,
// a positive integer if it's greater, and zero if they're equal.
//
// Invalid versions are less than all valid versions and equal to each other.
//
// SDK versions don't exactly follow the semantic versioning spec, so the
// built-in semver package cannot be used. The prerelease identifier is attached
// directly to the patch number instead of being separated by a dash
// ("0.26.0rc202604102"), and there is a ".dev1" suffix for local versions.
func Compare(sdkVersion1, sdkVersion2 string) int {
	v1, v1Valid := parse(sdkVersion1)
	v2, v2Valid := parse(sdkVersion2)

	switch {
	case !v1Valid && !v2Valid:
		return 0
	case !v1Valid && v2Valid:
		return -1
	case v1Valid && !v2Valid:
		return 1
	}

	if x := cmp.Compare(v1.Major, v2.Major); x != 0 {
		return x
	}
	if x := cmp.Compare(v1.Minor, v2.Minor); x != 0 {
		return x
	}
	if x := cmp.Compare(v1.Patch, v2.Patch); x != 0 {
		return x
	}

	// X.Y.Z.dev1 < X.Y.Zrc < X.Y.Z
	v1Dev, v2Dev := v1.DotDev != "", v2.DotDev != ""
	v1Pre, v2Pre := v1.Pre != "", v2.Pre != ""

	switch {
	case v1Dev && !v2Dev:
		return -1
	case v2Dev && !v1Dev:
		return 1

	// All dev versions for the same Major/Minor/Patch are equal,
	// regardless of the prerelease identifier. In practice, dev versions
	// are never prerelease versions.
	case v1Dev && v2Dev:
		return 0

	case v1Pre && !v2Pre:
		return -1
	case v2Pre && !v1Pre:
		return 1

	default:
		return 0
	}
}

// PyPI returns the PyPI format of the SDK version.
//
// The Header record in .wandb files includes a commit hash in the version,
// which is useful for debugging but not for identifying the PyPI package.
//
// Strings that aren't valid SDK versions are returned as-is.
func PyPI(sdkVersion string) string {
	parsed, valid := parse(sdkVersion)

	if !valid {
		return sdkVersion
	}

	return parsed.PyPI()
}

type parsedVersion struct {
	Major, Minor, Patch int64

	Pre    string
	DotDev string // "" if not dev version, else starts with dot like ".dev1"
}

// PyPI returns the PyPI representation of the version.
func (v parsedVersion) PyPI() string {
	return fmt.Sprintf("%d.%d.%d%s%s",
		v.Major, v.Minor, v.Patch, v.Pre, v.DotDev)
}

// Based on our .bumpversion.cfg, but less restrictive.
//
// Even if you change .bumpversion.cfg, this has to work for past versions!
var sdkVersionRe = regexp.MustCompile(
	`^(\d+)\.(\d+)\.(\d+)([a-z]+\d*)?(\.\w+)?`,
)

func parse(sdkVersion string) (parsedVersion, bool) {
	groups := sdkVersionRe.FindStringSubmatch(sdkVersion)

	if len(groups) != 6 {
		return parsedVersion{}, false
	}

	result := parsedVersion{}
	result.Major, _ = strconv.ParseInt(groups[1], 10, 64)
	result.Minor, _ = strconv.ParseInt(groups[2], 10, 64)
	result.Patch, _ = strconv.ParseInt(groups[3], 10, 64)

	result.Pre = groups[4]    // may be empty
	result.DotDev = groups[5] // may be empty

	return result, true
}
