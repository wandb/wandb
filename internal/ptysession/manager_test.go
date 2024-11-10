package ptysession

import (
	"testing"
	"time"
)

func TestManager(t *testing.T) {
	manager := GetManager()

	// Test adding and getting a session
	session, err := StartSession()
	if err != nil {
		t.Fatalf("Failed to start session: %v", err)
	}

	t.Run("AddSession and GetSession", func(t *testing.T) {
		manager.AddSession(session)

		got, exists := manager.GetSession(session.ID)
		if !exists {
			t.Error("Session should exist")
		}
		if got != session {
			t.Error("Got wrong session")
		}
	})

	t.Run("ListSessions", func(t *testing.T) {
		sessions := manager.ListSessions()
		found := false
		for _, id := range sessions {
			if id == session.ID {
				found = true
				break
			}
		}
		if !found {
			t.Error("Session ID not found in list")
		}
	})

	t.Run("RemoveSession", func(t *testing.T) {
		manager.RemoveSession(session.ID)
		_, exists := manager.GetSession(session.ID)
		if exists {
			t.Error("Session should not exist after removal")
		}
	})

	t.Run("SessionCleaner", func(t *testing.T) {
		session, _ := StartSession()
		manager.AddSession(session)

		// Set last activity to be older than timeout
		session.LastActivity = time.Now().Add(-2 * time.Minute)

		manager.StartSessionCleaner(time.Minute)

		// Wait for cleaner to run
		time.Sleep(2 * time.Second)

		_, exists := manager.GetSession(session.ID)
		if exists {
			t.Error("Inactive session should have been cleaned up")
		}
	})
}
