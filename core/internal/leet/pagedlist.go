package leet

// PagedList represents a paginated list of items.
type PagedList[T any] struct {
	Title         string
	Items         []T
	FilteredItems []T

	itemsPerPage int
	currentPage  int
	currentLine  int

	Height int
	Active bool
}

func (s *PagedList[T]) ItemsPerPage() int {
	return s.itemsPerPage
}
func (s *PagedList[T]) CurrentPage() int {
	return s.currentPage
}
func (s *PagedList[T]) CurrentLine() int {
	return s.currentLine
}

func (s *PagedList[T]) SetItemsPerPage(n int) {
	if n < 0 {
		n = 0
	}
	s.itemsPerPage = n

	s.clampCursor()
}

// Up navigates to previous item.
func (s *PagedList[T]) Up() {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	s.currentLine--

	// Still on the same page?
	if s.currentLine >= 0 {
		return
	}

	totalPages := s.totalPages()

	s.currentPage--

	if s.currentPage >= 0 {
		// Moved to previous page - go to last line.
		s.currentLine = s.itemsOnPage(s.currentPage) - 1
		return
	}

	// Wrapped around to last page.
	s.currentPage = totalPages - 1
	s.currentLine = s.itemsOnPage(s.currentPage) - 1
}

// Down navigates to next item.
func (s *PagedList[T]) Down() {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	s.currentLine++

	itemsOnPage := s.itemsOnPage(s.currentPage)
	if s.currentLine < itemsOnPage {
		return
	}

	// Move to next page - go to first line.
	s.currentPage++
	s.currentLine = 0

	// Wrapped around to first page.
	if s.currentPage >= s.totalPages() {
		s.currentPage = 0
	}
}

// PageUp navigates to previous page.
func (s *PagedList[T]) PageUp() {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	s.currentLine = 0
	s.currentPage--

	if s.currentPage < 0 {
		s.currentPage = s.totalPages() - 1
	}
}

// PageDown navigates to next page.
func (s *PagedList[T]) PageDown() {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	s.currentLine = 0
	s.currentPage++

	if s.currentPage >= s.totalPages() {
		s.currentPage = 0
	}
}

// Home navigates to start page.
func (s *PagedList[T]) Home() {
	s.currentPage = 0
	s.currentLine = 0
}

// End navigates to the last item on the last page.
func (s *PagedList[T]) End() {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	totalPages := s.totalPages()
	s.currentPage = totalPages - 1
	s.currentLine = s.itemsOnPage(s.currentPage) - 1
}

func (s *PagedList[T]) SetPageAndLine(page, line int) {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	totalPages := s.totalPages()
	if page < 0 || page > totalPages-1 {
		return
	}

	itemsOnPage := s.itemsOnPage(page)
	if line < 0 || line > itemsOnPage-1 {
		return
	}

	s.currentPage = page
	s.currentLine = line
}

func (s *PagedList[T]) CurrentItem() (T, bool) {
	var zero T
	if !s.hasNavigableItems() {
		return zero, false
	}

	start := s.currentPage * s.itemsPerPage
	idx := start + s.currentLine
	if idx < 0 || idx >= len(s.FilteredItems) {
		return zero, false
	}
	return s.FilteredItems[idx], true
}

// CurrentIndex returns the index of the selected item within
// FilteredItems, or -1 when there is no selection.
func (s *PagedList[T]) CurrentIndex() int {
	if !s.hasNavigableItems() {
		return -1
	}
	idx := s.currentPage*s.itemsPerPage + s.currentLine
	if idx < 0 || idx >= len(s.FilteredItems) {
		return -1
	}
	return idx
}

// PageBounds returns the half-open range of FilteredItems visible on the
// current page.
func (s *PagedList[T]) PageBounds() (start, end int) {
	if !s.hasNavigableItems() {
		return 0, 0
	}
	start = s.currentPage * s.itemsPerPage
	end = min(start+s.itemsPerPage, len(s.FilteredItems))
	return start, end
}

func (s *PagedList[T]) hasNavigableItems() bool {
	return s.itemsPerPage > 0 && len(s.FilteredItems) > 0
}

func (s *PagedList[T]) totalPages() int {
	if !s.hasNavigableItems() {
		return 0
	}
	return (len(s.FilteredItems) + s.itemsPerPage - 1) / s.itemsPerPage
}

func (s *PagedList[T]) itemsOnPage(page int) int {
	if !s.hasNavigableItems() {
		return 0
	}
	itemsOnPage := s.itemsPerPage
	if page == s.totalPages()-1 {
		if remainder := len(s.FilteredItems) % s.itemsPerPage; remainder != 0 {
			itemsOnPage = remainder
		}
	}
	return itemsOnPage
}

func (s *PagedList[T]) clampCursor() {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	totalPages := s.totalPages()
	if s.currentPage >= totalPages {
		s.currentPage = totalPages - 1
	}
	if s.currentPage < 0 {
		s.currentPage = 0
	}

	itemsOnPage := s.itemsOnPage(s.currentPage)
	if s.currentLine >= itemsOnPage {
		s.currentLine = itemsOnPage - 1
	}
	if s.currentLine < 0 {
		s.currentLine = 0
	}
}

func (s *PagedList[T]) resetCursor() {
	s.currentPage = 0
	s.currentLine = 0
}
