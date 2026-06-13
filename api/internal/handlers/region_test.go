package handlers

import (
	"testing"

	"github.com/omega-realm/api/internal/models"
)

func TestOnlineRegionsKeepsHeartbeatBackedOnlineRegion(t *testing.T) {
	region := models.GetRegionDetails(models.RegionLocal)
	region.Status = models.RegionStatusOnline

	online := onlineRegions([]*models.Region{region}, map[string]bool{models.RegionLocal: true})

	if len(online) != 1 || online[0].ID != models.RegionLocal {
		t.Fatalf("expected [local], got %v", online)
	}
}

func TestOnlineRegionsDropsRegionWithoutHeartbeat(t *testing.T) {
	// Static region details default to online; without a fresh heartbeat the
	// region must still be treated as offline.
	region := models.GetRegionDetails(models.RegionLocal)

	online := onlineRegions([]*models.Region{region}, map[string]bool{})

	if len(online) != 0 {
		t.Fatalf("expected no online regions, got %v", online)
	}
}

func TestOnlineRegionsDropsHeartbeatBackedRegionReportingNotOnline(t *testing.T) {
	for _, status := range []string{models.RegionStatusOffline, models.RegionStatusMaintenance} {
		region := models.GetRegionDetails(models.RegionLocal)
		region.Status = status

		online := onlineRegions([]*models.Region{region}, map[string]bool{models.RegionLocal: true})

		if len(online) != 0 {
			t.Fatalf("status %q: expected no online regions, got %v", status, online)
		}
	}
}
