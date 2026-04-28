package models

import "testing"

func TestLocalRegionUsesGameServerCapacity(t *testing.T) {
	region := GetRegionDetails(RegionLocal)
	if region == nil {
		t.Fatal("expected local region")
	}
	if region.MaxPlayers != 100 {
		t.Fatalf("expected local max players to be 100, got %d", region.MaxPlayers)
	}
}
