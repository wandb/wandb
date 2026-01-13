# Changelog

## [0.6.1]

[Compare](https://github.com/clipperhouse/displaywidth/compare/v0.6.0...v0.6.1)

### Changed
- Perf improvements: replaced the ASCII lookup table with a simple
  function. A bit more cache-friendly. More inlining.
- Bug fix: single regional indicators are now treated as width 2, since that
  is what actual terminals do.

## [0.6.0]

[Compare](https://github.com/clipperhouse/displaywidth/compare/v0.5.0...v0.6.0)

### Added
- New `StringGraphemes` and `BytesGraphemes` methods, for iterating over the
widths of grapheme clusters.

### Changed
- Added ASCII fast paths

## [0.5.0]

[Compare](https://github.com/clipperhouse/displaywidth/compare/v0.4.1...v0.5.0)

### Added
- Unicode 16 support
- Improved emoji presentation handling per Unicode TR51

### Changed
- Corrected VS15 (U+FE0E) handling: now preserves base character width (no-op) per Unicode TR51
- Performance optimizations: reduced property lookups

### Fixed
- VS15 variation selector now correctly preserves base character width instead of forcing width 1

## [0.4.1]

[Compare](https://github.com/clipperhouse/displaywidth/compare/v0.4.0...v0.4.1)

### Changed
- Updated uax29 dependency
- Improved flag handling

## [0.4.0]

[Compare](https://github.com/clipperhouse/displaywidth/compare/v0.3.1...v0.4.0)

### Added
- Support for variation selectors (VS15, VS16) and regional indicator pairs (flags)

## [0.3.1]

[Compare](https://github.com/clipperhouse/displaywidth/compare/v0.3.0...v0.3.1)

### Added
- Fuzz testing support

### Changed
- Updated stringish dependency

## [0.3.0]

[Compare](https://github.com/clipperhouse/displaywidth/compare/v0.2.0...v0.3.0)

### Changed
- Dropped compatibility with go-runewidth
- Trie implementation cleanup
