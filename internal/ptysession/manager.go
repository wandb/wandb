package ptysession

import (
	"log"
	"sync"
	"time"
)

// Manager handles concurrent access to PTY sessions
type Manager struct {
	sessions map[string]*Session
	mu       sync.RWMutex
}

var (
	// Singleton instance of the session manager
	manager     *Manager
	managerOnce sync.Once
)

// GetManager returns the singleton instance of the session manager. It
// initializes the manager on first call using sync.Once.
func GetManager() *Manager {
	managerOnce.Do(func() {
		manager = &Manager{
			sessions: make(map[string]*Session),
		}
	})
	return manager
}

// AddSession adds a new PTY session to the manager. It acquires a write lock to
// safely add the session to the map.
func (m *Manager) AddSession(session *Session) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sessions[session.ID] = session
}

// GetSession retrieves a session by its ID. It returns the session and a
// boolean indicating if it exists. Uses a read lock since it doesn't modify the
// sessions map.
func (m *Manager) GetSession(id string) (*Session, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	session, exists := m.sessions[id]
	return session, exists
}

// RemoveSession removes a session from the manager. It acquires a write lock to
// safely delete the session from the map.
func (m *Manager) RemoveSession(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.sessions, id)
}

// ListSessions returns a list of active session IDs. It acquires a read lock
// since it only reads from the sessions map. Returns a slice containing all
// session IDs.
func (m *Manager) ListSessions() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	ids := make([]string, 0, len(m.sessions))
	for id := range m.sessions {
		ids = append(ids, id)
	}
	return ids
}

func (m *Manager) StartSessionCleaner(timeout time.Duration) {
	go func() {
		log.Printf("Starting session cleaner with timeout %v", timeout)
		for {
			time.Sleep(timeout / 2)
			m.mu.Lock()
			for id, session := range m.sessions {
				idleTime := time.Since(session.LastActivity)
				if idleTime > timeout {
					log.Printf("Cleaning up inactive session %s (idle for %v)", id, idleTime)
					session.CancelFunc()
					delete(m.sessions, id)
				}
			}
			m.mu.Unlock()
		}
	}()
}
