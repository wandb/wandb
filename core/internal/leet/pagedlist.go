package leet

// PagedList represents a paginated list of items.
type PagedList struct {
	Title         string
	Items         []KeyValuePair // TODO: use pointers
	FilteredItems []KeyValuePair

	itemsPerPage int
	currentPage  int
	currentLine  int

	Height int
	Active bool
}

func (s *PagedList) ItemsPerPage() int {
	return s.itemsPerPage
}
func (s *PagedList) CurrentPage() int {
	return s.currentPage
}
func (s *PagedList) CurrentLine() int {
	return s.currentLine
}

func (s *PagedList) SetItemsPerPage(n int) {
	if n < 0 {
		n = 0
	}
	s.itemsPerPage = n

	s.clampCursor()
}

// Up navigates to previous item.
func (s *PagedList) Up() {
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
func (s *PagedList) Down() {
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
func (s *PagedList) PageUp() {
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
func (s *PagedList) PageDown() {
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
func (s *PagedList) Home() {
	s.currentPage = 0
	s.currentLine = 0
}

// End navigates to the last item on the last page.
func (s *PagedList) End() {
	if !s.hasNavigableItems() {
		s.resetCursor()
		return
	}

	totalPages := s.totalPages()
	s.currentPage = totalPages - 1
	s.currentLine = s.itemsOnPage(s.currentPage) - 1
}

func (s *PagedList) SetPageAndLine(page, line int) {
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

func (s *PagedList) CurrentItem() (KeyValuePair, bool) {
	if !s.hasNavigableItems() {
		return KeyValuePair{}, false
	}

	start := s.currentPage * s.itemsPerPage
	idx := start + s.currentLine
	if idx < 0 || idx >= len(s.FilteredItems) {
		return KeyValuePair{}, false
	}
	return s.FilteredItems[idx], true
}

func (s *PagedList) hasNavigableItems() bool {
	return s.itemsPerPage > 0 && len(s.FilteredItems) > 0
}

func (s *PagedList) totalPages() int {
	if !s.hasNavigableItems() {
		return 0
	}
	return (len(s.FilteredItems) + s.itemsPerPage - 1) / s.itemsPerPage
}

func (s *PagedList) itemsOnPage(page int) int {
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

func (s *PagedList) clampCursor() {
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

func (s *PagedList) resetCursor() {
	s.currentPage = 0
	s.currentLine = 0
}
