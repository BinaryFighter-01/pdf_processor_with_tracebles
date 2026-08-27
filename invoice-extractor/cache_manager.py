"""
Result Caching Manager
Handles caching of extraction results to avoid re-processing identical files
"""

import os
import json
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from langsmith import traceable


class CacheManager:
    """Manages caching of invoice extraction results."""
    
    def __init__(self, cache_dir: str = "uploads/.cache", max_age_hours: int = 24):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory to store cache files
            max_age_hours: Maximum age of cache entries in hours (0 = no expiry)
        """
        self.cache_dir = Path(cache_dir)
        self.max_age_hours = max_age_hours
        
        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_cache_key(self, file_bytes: bytes, options: Dict[str, Any]) -> str:
        """
        Generate a unique cache key from file contents and extraction options.
        
        Args:
            file_bytes: Raw file bytes
            options: Dictionary of extraction options (use_ocr, two_pass, multi_page, etc.)
        
        Returns:
            SHA-256 hex digest as cache key
        """
        hasher = hashlib.sha256()
        
        # Hash file content
        hasher.update(file_bytes)
        
        # Hash extraction options (sorted for consistency)
        options_json = json.dumps(options, sort_keys=True)
        hasher.update(options_json.encode('utf-8'))
        
        return hasher.hexdigest()
    
    @traceable(name="cache_get", tags=["cache", "read"])
    def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached result if it exists and is not expired.
        
        Args:
            cache_key: Cache key to lookup
        
        Returns:
            Cached result dict or None if not found/expired
        """
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            # Read cache file
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            
            # Check age if max_age_hours is set
            if self.max_age_hours > 0:
                cached_time = cached_data.get('cached_at', 0)
                age_seconds = time.time() - cached_time
                age_hours = age_seconds / 3600
                
                if age_hours > self.max_age_hours:
                    print(f"🗑️  Cache entry expired (age: {age_hours:.1f}h > {self.max_age_hours}h)")
                    # Delete expired entry
                    cache_file.unlink()
                    return None
            
            print(f"✅ Cache hit: {cache_key[:16]}... (age: {self._get_age_str(cached_data.get('cached_at', 0))})")
            return cached_data.get('result')
        
        except (json.JSONDecodeError, KeyError, OSError) as e:
            print(f"⚠️  Corrupted cache file, deleting: {e}")
            try:
                cache_file.unlink()
            except:
                pass
            return None
    
    @traceable(name="cache_set", tags=["cache", "write"])
    def set(self, cache_key: str, result: Dict[str, Any], metadata: Dict[str, Any] = None) -> bool:
        """
        Store extraction result in cache.
        
        Args:
            cache_key: Cache key
            result: Extraction result to cache
            metadata: Optional metadata (filename, options, etc.)
        
        Returns:
            True if successful, False otherwise
        """
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        try:
            cache_data = {
                'cache_key': cache_key,
                'cached_at': time.time(),
                'result': result,
                'metadata': metadata or {}
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            size_kb = cache_file.stat().st_size / 1024
            print(f"💾 Cached result: {cache_key[:16]}... ({size_kb:.1f}KB)")
            return True
        
        except (OSError, TypeError) as e:
            print(f"❌ Failed to cache result: {e}")
            return False
    
    def clear(self, max_age_hours: Optional[int] = None) -> Dict[str, int]:
        """
        Clear cache entries.
        
        Args:
            max_age_hours: If specified, only delete entries older than this age.
                          If None, delete all entries.
        
        Returns:
            Dict with 'deleted_count' and 'freed_space_bytes'
        """
        deleted_count = 0
        freed_space = 0
        
        if not self.cache_dir.exists():
            return {'deleted_count': 0, 'freed_space_bytes': 0}
        
        cutoff_time = None
        if max_age_hours is not None:
            cutoff_time = time.time() - (max_age_hours * 3600)
        
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                # If max_age specified, check file age
                if cutoff_time is not None:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached_data = json.load(f)
                    cached_at = cached_data.get('cached_at', 0)
                    
                    if cached_at > cutoff_time:
                        continue  # Skip, not old enough
                
                # Delete file
                size = cache_file.stat().st_size
                cache_file.unlink()
                deleted_count += 1
                freed_space += size
            
            except (OSError, json.JSONDecodeError):
                # Skip files we can't process
                continue
        
        print(f"🗑️  Cleared {deleted_count} cache entries, freed {freed_space / 1024:.1f}KB")
        return {
            'deleted_count': deleted_count,
            'freed_space_bytes': freed_space
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dict with total_entries, total_size_bytes, oldest_entry_age_hours, newest_entry_age_hours
        """
        if not self.cache_dir.exists():
            return {
                'total_entries': 0,
                'total_size_bytes': 0,
                'oldest_entry_age_hours': 0,
                'newest_entry_age_hours': 0
            }
        
        entries = list(self.cache_dir.glob("*.json"))
        total_size = 0
        oldest_time = None
        newest_time = None
        
        for cache_file in entries:
            try:
                total_size += cache_file.stat().st_size
                
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                cached_at = cached_data.get('cached_at', 0)
                
                if oldest_time is None or cached_at < oldest_time:
                    oldest_time = cached_at
                if newest_time is None or cached_at > newest_time:
                    newest_time = cached_at
            
            except (OSError, json.JSONDecodeError):
                continue
        
        current_time = time.time()
        oldest_age = (current_time - oldest_time) / 3600 if oldest_time else 0
        newest_age = (current_time - newest_time) / 3600 if newest_time else 0
        
        return {
            'total_entries': len(entries),
            'total_size_bytes': total_size,
            'oldest_entry_age_hours': round(oldest_age, 2),
            'newest_entry_age_hours': round(newest_age, 2)
        }
    
    @staticmethod
    def _get_age_str(cached_at: float) -> str:
        """Get human-readable age string."""
        age_seconds = time.time() - cached_at
        if age_seconds < 60:
            return f"{int(age_seconds)}s"
        elif age_seconds < 3600:
            return f"{int(age_seconds / 60)}m"
        else:
            return f"{age_seconds / 3600:.1f}h"
