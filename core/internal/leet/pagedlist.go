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
	if n <= 0 {
		n = 1
	}
	s.itemsPerPage = n

	// Clamp currentPage so it stays valid after the page size changes.
	totalItems := len(s.FilteredItems)
	if totalItems == 0 {
		s.currentPage = 0
		s.currentLine = 0
		return
	}
	totalPages := (totalItems + s.itemsPerPage - 1) / s.itemsPerPage
	if s.currentPage >= totalPages {
		s.currentPage = totalPages - 1
	}
	// Also clamp currentLine to the items available on the (now‑valid) page.
	itemsOnPage := s.itemsPerPage
	if s.currentPage == totalPages-1 {
		if remainder := totalItems % s.itemsPerPage; remainder != 0 {
			itemsOnPage = remainder
		}
	}
	if s.currentLine >= itemsOnPage {
		s.currentLine = itemsOnPage - 1
	}
}

// Up navigates to previous item.
func (s *PagedList) Up() {
	s.currentLine--

	// Still on the same page?
	if s.currentLine >= 0 {
		return
	}

	totalItems := len(s.FilteredItems)
	totalPages := (totalItems + s.itemsPerPage - 1) / s.itemsPerPage

	s.currentPage--

	if s.currentPage >= 0 {
		// Moved to previous page - go to last line.
		s.currentLine = s.itemsPerPage - 1
		return
	}

	// Wrapped around to last page.
	s.currentPage = totalPages - 1
	if remainder := totalItems % s.itemsPerPage; remainder == 0 {
		s.currentLine = s.itemsPerPage - 1
	} else {
		s.currentLine = remainder - 1
	}
}

// Down navigates to next item.
func (s *PagedList) Down() {
	s.currentLine++

	totalItems := len(s.FilteredItems)
	totalPages := (totalItems + s.itemsPerPage - 1) / s.itemsPerPage

	itemsOnPage := s.itemsPerPage
	if s.currentPage == totalPages-1 {
		if remainder := totalItems % s.itemsPerPage; remainder != 0 {
			itemsOnPage = remainder
		}
	}

	if s.currentLine < itemsOnPage {
		return
	}

	// Move to next page - go to first line.
	s.currentPage++
	s.currentLine = 0

	// Wrapped around to first page.
	if s.currentPage >= totalPages {
		s.currentPage = 0
	}
}

// PageUp navigates to previous page.
func (s *PagedList) PageUp() {
	s.currentLine = 0
	s.currentPage--

	totalItems := len(s.FilteredItems)
	totalPages := (totalItems + s.itemsPerPage - 1) / s.itemsPerPage

	if s.currentPage < 0 {
		s.currentPage = totalPages - 1
	}
}

// PageDown navigates to next page.
func (s *PagedList) PageDown() {
	s.currentLine = 0
	s.currentPage++

	totalItems := len(s.FilteredItems)
	totalPages := (totalItems + s.itemsPerPage - 1) / s.itemsPerPage

	if s.currentPage >= totalPages {
		s.currentPage = 0
	}
}

// Home navigates to start page.
func (s *PagedList) Home() {
	s.currentPage = 0
	s.currentLine = 0
}

func (s *PagedList) SetPageAndLine(page, line int) {
	totalItems := len(s.FilteredItems)
	totalPages := (totalItems + s.itemsPerPage - 1) / s.itemsPerPage

	if page < 0 || page > totalPages-1 {
		return
	}

	itemsOnPage := s.itemsPerPage
	if page == totalPages-1 {
		if remainder := totalItems % s.itemsPerPage; remainder != 0 {
			itemsOnPage = remainder
		}
	}

	if line < 0 || line > itemsOnPage-1 {
		return
	}

	s.currentPage = page
	s.currentLine = line
}

func (s *PagedList) CurrentItem() (KeyValuePair, bool) {
	totalItems := len(s.FilteredItems)
	start := s.currentPage * s.itemsPerPage
	idx := start + s.currentLine
	if idx < 0 || idx >= totalItems {
		return KeyValuePair{}, false
	}
	return s.FilteredItems[idx], true
}
