package core

import (
	"fmt"
	"sync"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/gqlerror"
)

type sourceCapture struct {
	locations []gqlerror.SourceLocation
}

// sourceCaptures bridges the legacy ErrorOption API: At receives only an
// *gqlerror.Error and cannot access CaptureSourceLocations' local capture.
// Entries exist only while source-aware options are being applied.
var sourceCaptures sync.Map // map[*gqlerror.Error]*sourceCapture

// CaptureSourceLocations applies error options while recording the source
// documents supplied to At. It returns source-aware locations in the same
// order as err.Locations.
// Source-aware validation uses this helper; the regular validation API does
// not install a capture and keeps its existing behavior.
func CaptureSourceLocations(err *gqlerror.Error, apply func()) []gqlerror.SourceLocation {
	if err == nil {
		panic("gqlparser: cannot capture source locations for a nil error")
	}
	capture := &sourceCapture{}
	sourceCaptures.Store(err, capture)
	defer sourceCaptures.Delete(err)

	apply()
	if len(err.Locations) == 0 {
		if len(capture.locations) > 0 {
			panic(fmt.Sprintf(
				"gqlparser: captured source location %d does not match the final error locations",
				0,
			))
		}
		return nil
	}
	locations := make([]gqlerror.SourceLocation, len(err.Locations))
	for i, location := range err.Locations {
		locations[i] = gqlerror.SourceLocation{
			Line:   location.Line,
			Column: location.Column,
		}
	}
	recorded := 0
	for i, location := range err.Locations {
		if recorded == len(capture.locations) {
			break
		}
		captured := capture.locations[recorded]
		if captured.Line != location.Line || captured.Column != location.Column {
			continue
		}
		locations[i].Source = captured.Source
		recorded++
	}
	if recorded != len(capture.locations) {
		panic(fmt.Sprintf(
			"gqlparser: captured source location %d does not match the final error locations",
			recorded,
		))
	}
	return locations
}

func recordSourceLocation(err *gqlerror.Error, location gqlerror.Location, source *ast.Source) {
	value, ok := sourceCaptures.Load(err)
	if !ok {
		return
	}
	capture := value.(*sourceCapture)
	capture.locations = append(capture.locations, gqlerror.SourceLocation{
		Line:   location.Line,
		Column: location.Column,
		Source: source,
	})
}
