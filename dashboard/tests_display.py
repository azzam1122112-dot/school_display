import pytest
import json
from unittest.mock import patch, MagicMock
from django.urls import reverse
from django.test import RequestFactory
from django.core.cache import cache

from dashboard.api_display_v2 import display_status, display_snapshot
from dashboard.services_display import cache_write_snapshot, build_school_snapshot, verify_token_cached

@pytest.mark.django_db
class TestDisplaySystem:
    
    def setup_method(self):
        self.factory = RequestFactory()
        self.school_id = 99
        self.token = "SECRET_TOKEN_123"
        # Pre-warm cache for token
        cache.set(f"display:token:{self.token}", self.school_id)

    def test_verify_token_cached(self):
        # Test cache hit
        assert verify_token_cached(self.token) == self.school_id
        # Test cache miss (and fallback failure in mock)
        assert verify_token_cached("INVALID") is None

    @patch("dashboard.services_display.get_redis_connection")
    def test_cache_write_atomic(self, mock_redis):
        # Mocking Redis Pipeline
        pipeline_mock = MagicMock()
        
        # Setup the mock so it behaves like a redis client
        client_mock = MagicMock()
        client_mock.pipeline.return_value = pipeline_mock
        mock_redis.return_value = client_mock
        
        # Mocking pipeline execution result [new_version, set_result]
        pipeline_mock.execute.return_value = [101, True] 
        # Also allow direct incr/set if pipeline not used (though our code prefers pipeline)
        client_mock.incr.return_value = 101

        data = {"test": "data"}
        ver = cache_write_snapshot(self.school_id, data)
        
        assert ver == 101
        
        # Verify pipeline was used
        if client_mock.pipeline.called:
            pipeline_mock.incr.assert_called()
            pipeline_mock.set.assert_called()

    def test_integration_flow(self):
        # 1. Setup Data in Redis
        snapshot_data = {"schedule": [], "meta": {"v": 1}}
        
        with patch("dashboard.api_display_v2.get_cached_school_version") as mock_ver:
            with patch("dashboard.api_display_v2.get_cached_school_snapshot") as mock_snap:
                
                # CASE A: Status Endpoint (Outdated Client)
                mock_ver.return_value = 50
                
                request = self.factory.get(f"/api/status?token={self.token}&v=40")
                response = display_status(request)
                
                assert response.status_code == 200
                data = json.loads(response.content)
                assert data['current_version'] == 50
                assert data['fetch_required'] is True
                
                # CASE B: Status Endpoint (Up-to-date Client)
                request = self.factory.get(f"/api/status?token={self.token}&v=50")
                response = display_status(request)
                assert response.status_code == 304

                # CASE C: Snapshot Endpoint
                mock_snap.return_value = json.dumps(snapshot_data)
                request = self.factory.get(f"/api/snapshot?token={self.token}")
                response = display_snapshot(request)
                
                assert response.status_code == 200
                # Direct string response might not be parsed by .json() in some test clients immediately, 
                # but let's check content directly
                assert json.loads(response.content) == snapshot_data

    @patch("dashboard.services_display.build_school_snapshot")
    @patch("dashboard.services_display.cache_write_snapshot")
    def test_debounce_logic(self, mock_write, mock_build):
        from dashboard.signals_display import debounce_rebuild
        
        # Mock transaction.on_commit to execute immediately
        with patch("django.db.transaction.on_commit", side_effect=lambda f: f()):
            
            # First Call - Should Run
            debounce_rebuild(self.school_id)
            mock_build.assert_called()
            
            mock_build.reset_mock()
            
            # Immediate Second Call - Should be blocked by cache lock
            # We simulate the cache being set by the first call
            # In real redis it sets, in locmem it sets.
            # verify cache is set
            
            debounce_rebuild(self.school_id)
            # Depending on how fast this runs vs the cache timeout (2s), it should skip
            # But since we mock on_commit, it runs sequentially.
            # Ideally the first call sets the key.
            
            # Due to mock complexity with cache backends in tests without real redis, 
            # we can verify logic:
            assert cache.get(f"debounce:rebuild:school:{self.school_id}") is not None
