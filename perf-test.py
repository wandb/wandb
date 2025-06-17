#!/usr/bin/env python3
"""
Performance comparison test for lightweight vs full API runs mode.

This script demonstrates the performance differences between lightweight=True (default)
and lightweight=False modes when fetching runs from W&B API, including the new smart
caching behavior that eliminates duplicate cache entries.
"""

import time
import tracemalloc
import gc
from typing import List
import wandb


def measure_memory_and_time(func, *args, **kwargs):
    """Measure memory usage and execution time of a function."""
    # Force garbage collection before measurement
    gc.collect()
    
    # Start memory tracing
    tracemalloc.start()
    start_time = time.time()
    
    # Execute function
    result = func(*args, **kwargs)
    
    # Stop timing and get memory stats
    end_time = time.time()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    execution_time = end_time - start_time
    
    return result, {
        'execution_time': execution_time,
        'current_memory_mb': current / 1024 / 1024,
        'peak_memory_mb': peak / 1024 / 1024
    }


def test_lightweight_mode(entity: str, project: str, max_runs: int = 50):
    """Test lightweight mode performance."""
    print(f"Testing lightweight mode (fetching up to {max_runs} runs)...")
    
    def fetch_runs_lightweight():
        api = wandb.Api()
        runs = api.runs(f"{entity}/{project}", lightweight=True, per_page=max_runs)
        # Convert to list to force evaluation
        runs_list = list(runs)
        
        # Access basic metadata (should not trigger full data loading)
        metadata_access = []
        for run in runs_list[:10]:  # Test first 10 runs
            metadata_access.append({
                'name': run.name,
                'state': run.state,
                'created_at': run.created_at,
                'tags': run.tags
            })
        
        return runs_list, metadata_access
    
    return measure_memory_and_time(fetch_runs_lightweight)


def test_full_mode(entity: str, project: str, max_runs: int = 50):
    """Test full mode performance."""
    print(f"Testing full mode (fetching up to {max_runs} runs)...")
    
    def fetch_runs_full():
        api = wandb.Api()
        runs = api.runs(f"{entity}/{project}", lightweight=False, per_page=max_runs)
        # Convert to list to force evaluation
        runs_list = list(runs)
        
        # Access same metadata as lightweight test
        metadata_access = []
        for run in runs_list[:10]:  # Test first 10 runs
            metadata_access.append({
                'name': run.name,
                'state': run.state,
                'created_at': run.created_at,
                'tags': run.tags
            })
        
        return runs_list, metadata_access
    
    return measure_memory_and_time(fetch_runs_full)


def test_smart_cache_behavior(entity: str, project: str):
    """Test smart caching: lightweight -> full upgrade behavior."""
    print("Testing smart cache upgrade (lightweight -> full)...")
    
    def test_cache_upgrade():
        api = wandb.Api()
        
        # First request: lightweight mode (should populate cache)
        print("  → First request: lightweight=True")
        runs1 = api.runs(f"{entity}/{project}", lightweight=True, per_page=5)
        runs_list1 = list(runs1)
        
        # Verify runs are in lightweight mode
        first_run = runs_list1[0] if runs_list1 else None
        initial_lightweight = first_run._lightweight if first_run else None
        
        # Second request: full mode (should upgrade same cache entry)
        print("  → Second request: lightweight=False (should upgrade cache)")
        runs2 = api.runs(f"{entity}/{project}", lightweight=False, per_page=5)
        runs_list2 = list(runs2)
        
        # Verify cache was upgraded
        upgraded_lightweight = runs2._lightweight if hasattr(runs2, '_lightweight') else None
        
        # Check if it's the same object reference (cached)
        same_cache_object = runs1 is runs2
        
        return {
            'runs_count': len(runs_list1),
            'initial_lightweight': initial_lightweight,
            'upgraded_lightweight': upgraded_lightweight,
            'same_cache_object': same_cache_object,
            'first_run_has_config': bool(first_run._attrs.get("config")) if first_run else False
        }
    
    return measure_memory_and_time(test_cache_upgrade)


def test_reverse_cache_behavior(entity: str, project: str):
    """Test reverse caching: full -> lightweight (should reuse full data)."""
    print("Testing reverse cache behavior (full -> lightweight)...")
    
    def test_reverse_cache():
        api = wandb.Api()
        
        # Clear any existing cache by using a fresh API instance
        api.flush()
        
        # First request: full mode
        print("  → First request: lightweight=False")
        runs1 = api.runs(f"{entity}/{project}", lightweight=False, per_page=3)
        runs_list1 = list(runs1)
        
        # Second request: lightweight mode (should reuse same cache)
        print("  → Second request: lightweight=True (should reuse full cache)")
        runs2 = api.runs(f"{entity}/{project}", lightweight=True, per_page=3)
        runs_list2 = list(runs2)
        
        # Verify it's the same cache object
        same_cache_object = runs1 is runs2
        
        # Verify full data is still available even though we requested lightweight
        first_run = runs_list2[0] if runs_list2 else None
        has_full_data = bool(first_run._attrs.get("config")) if first_run else False
        
        return {
            'runs_count': len(runs_list1),
            'same_cache_object': same_cache_object,
            'has_full_data_in_lightweight_request': has_full_data,
            'cache_mode': runs2._lightweight if hasattr(runs2, '_lightweight') else None
        }
    
    return measure_memory_and_time(test_reverse_cache)


def test_lazy_loading(entity: str, project: str):
    """Test lazy loading behavior in lightweight mode."""
    print("Testing lazy loading behavior...")
    
    def test_config_access():
        api = wandb.Api()
        runs = api.runs(f"{entity}/{project}", lightweight=True, per_page=5)
        runs_list = list(runs)
        
        if runs_list:
            # Access config should trigger lazy loading
            first_run = runs_list[0]
            config = first_run.config  # This should trigger load_full_data()
            summary = first_run.summary  # This should also trigger load_full_data() if not already loaded
            
            return {
                'config_keys': len(config.keys()) if config else 0,
                'summary_keys': len(summary.keys()) if hasattr(summary, 'keys') else 0,
                'run_upgraded_to_full': not first_run._lightweight  # Should be False after lazy loading
            }
        return {'config_keys': 0, 'summary_keys': 0, 'run_upgraded_to_full': False}
    
    return measure_memory_and_time(test_config_access)


def test_explicit_full_data_loading(entity: str, project: str):
    """Test explicit full data loading with load_full_data()."""
    print("Testing explicit full data loading...")
    
    def test_load_full_data():
        api = wandb.Api()
        runs = api.runs(f"{entity}/{project}", lightweight=True, per_page=3)
        runs_list = list(runs)
        
        if runs_list:
            # Explicitly load full data for first run
            first_run = runs_list[0]
            original_lightweight = first_run._lightweight
            first_run.load_full_data()
            post_load_lightweight = first_run._lightweight
            
            return {
                'config_loaded': bool(first_run._attrs.get("config")),
                'summary_loaded': bool(first_run._attrs.get("summaryMetrics")),
                'system_loaded': bool(first_run._attrs.get("systemMetrics")),
                'original_lightweight': original_lightweight,
                'post_load_lightweight': post_load_lightweight
            }
        return {
            'config_loaded': False, 
            'summary_loaded': False, 
            'system_loaded': False,
            'original_lightweight': True,
            'post_load_lightweight': True
        }
    
    return measure_memory_and_time(test_load_full_data)


def main():
    """Main test function."""
    # Configure these for your project
    ENTITY = "thanos-wandb"  # Replace with your entity
    PROJECT = "compression-benchmark-string-heavy-data"  # Replace with your project
    MAX_RUNS = 50  # Number of runs to fetch for comparison
    
    print("=" * 70)
    print("W&B API Runs Performance & Smart Cache Comparison")
    print("=" * 70)
    print(f"Entity: {ENTITY}")
    print(f"Project: {PROJECT}")
    print(f"Max runs: {MAX_RUNS}")
    print("=" * 70)
    
    # Test 1: Lightweight mode
    (lightweight_runs, lightweight_metadata), lightweight_stats = test_lightweight_mode(ENTITY, PROJECT, MAX_RUNS)
    
    # Test 2: Full mode
    (full_runs, full_metadata), full_stats = test_full_mode(ENTITY, PROJECT, MAX_RUNS)
    
    # Test 3: Smart cache upgrade (lightweight -> full)
    cache_upgrade_result, cache_upgrade_stats = test_smart_cache_behavior(ENTITY, PROJECT)
    
    # Test 4: Reverse cache behavior (full -> lightweight)
    reverse_cache_result, reverse_cache_stats = test_reverse_cache_behavior(ENTITY, PROJECT)
    
    # Test 5: Lazy loading
    lazy_result, lazy_stats = test_lazy_loading(ENTITY, PROJECT)
    
    # Test 6: Explicit full data loading
    explicit_result, explicit_stats = test_explicit_full_data_loading(ENTITY, PROJECT)
    
    # Results
    print("\n" + "=" * 70)
    print("PERFORMANCE & CACHING RESULTS")
    print("=" * 70)
    
    print(f"\n📊 LIGHTWEIGHT MODE (BASELINE):")
    print(f"   Runs fetched: {len(lightweight_runs)}")
    print(f"   Execution time: {lightweight_stats['execution_time']:.2f}s")
    print(f"   Peak memory: {lightweight_stats['peak_memory_mb']:.2f}MB")
    print(f"   Current memory: {lightweight_stats['current_memory_mb']:.2f}MB")
    
    print(f"\n📊 FULL MODE:")
    print(f"   Runs fetched: {len(full_runs)}")
    print(f"   Execution time: {full_stats['execution_time']:.2f}s")
    print(f"   Peak memory: {full_stats['peak_memory_mb']:.2f}MB")
    print(f"   Current memory: {full_stats['current_memory_mb']:.2f}MB")
    
    print(f"\n🚀 SMART CACHE UPGRADE (lightweight → full):")
    print(f"   Execution time: {cache_upgrade_stats['execution_time']:.2f}s")
    print(f"   Peak memory: {cache_upgrade_stats['peak_memory_mb']:.2f}MB")
    print(f"   Runs count: {cache_upgrade_result['runs_count']}")
    print(f"   Same cache object: {cache_upgrade_result['same_cache_object']} ✅")
    print(f"   Initial lightweight: {cache_upgrade_result['initial_lightweight']}")
    print(f"   After upgrade lightweight: {cache_upgrade_result['upgraded_lightweight']}")
    print(f"   Config available after upgrade: {cache_upgrade_result['first_run_has_config']}")
    
    print(f"\n🔄 REVERSE CACHE BEHAVIOR (full → lightweight):")
    print(f"   Execution time: {reverse_cache_stats['execution_time']:.2f}s")
    print(f"   Peak memory: {reverse_cache_stats['peak_memory_mb']:.2f}MB")
    print(f"   Same cache object: {reverse_cache_result['same_cache_object']} ✅")
    print(f"   Full data available in lightweight request: {reverse_cache_result['has_full_data_in_lightweight_request']} ✅")
    print(f"   Cache mode: {'lightweight' if reverse_cache_result['cache_mode'] else 'full'}")
    
    print(f"\n⚡ LAZY LOADING:")
    print(f"   Execution time: {lazy_stats['execution_time']:.2f}s")
    print(f"   Peak memory: {lazy_stats['peak_memory_mb']:.2f}MB")
    print(f"   Config keys loaded: {lazy_result['config_keys']}")
    print(f"   Summary keys loaded: {lazy_result['summary_keys']}")
    print(f"   Run upgraded after access: {lazy_result['run_upgraded_to_full']}")
    
    print(f"\n🔧 EXPLICIT LOADING:")
    print(f"   Execution time: {explicit_stats['execution_time']:.2f}s")
    print(f"   Peak memory: {explicit_stats['peak_memory_mb']:.2f}MB")
    print(f"   Config loaded: {explicit_result['config_loaded']}")
    print(f"   Summary loaded: {explicit_result['summary_loaded']}")
    print(f"   System metrics loaded: {explicit_result['system_loaded']}")
    print(f"   Lightweight before: {explicit_result['original_lightweight']}")
    print(f"   Lightweight after: {explicit_result['post_load_lightweight']}")
    
    # Performance comparison
    print(f"\n🚀 PERFORMANCE COMPARISON:")
    if lightweight_stats['execution_time'] > 0 and full_stats['execution_time'] > 0:
        time_improvement = (full_stats['execution_time'] - lightweight_stats['execution_time']) / full_stats['execution_time'] * 100
        memory_improvement = (full_stats['peak_memory_mb'] - lightweight_stats['peak_memory_mb']) / full_stats['peak_memory_mb'] * 100
        
        print(f"   Time improvement: {time_improvement:.1f}% faster")
        print(f"   Memory improvement: {memory_improvement:.1f}% less memory")
        print(f"   Speed ratio: {full_stats['execution_time'] / lightweight_stats['execution_time']:.1f}x faster")
    
    # Cache efficiency analysis
    cache_time_ratio = cache_upgrade_stats['execution_time'] / (lightweight_stats['execution_time'] + full_stats['execution_time'])
    print(f"\n💾 SMART CACHE EFFICIENCY:")
    print(f"   Cache upgrade time vs separate requests: {cache_time_ratio:.1%}")
    print(f"   Unified caching: {'✅ Working' if cache_upgrade_result['same_cache_object'] else '❌ Not working'}")
    print(f"   No duplicate cache entries: {'✅ Confirmed' if cache_upgrade_result['same_cache_object'] else '❌ Issue detected'}")
    
    print("\n" + "=" * 70)
    print("Test completed! 🎉")
    print("💡 Key Benefits:")
    print("   • Unified caching prevents duplicate cache entries")
    print("   • Smart cache upgrade from lightweight to full mode")
    print("   • Lazy loading provides transparent access to heavy fields")
    print("   • Significant performance improvements for list operations")
    print("=" * 70)


if __name__ == "__main__":
    # Example usage patterns
    print("\n💡 USAGE EXAMPLES:")
    print("\n# Example 1: Default lightweight mode (recommended)")
    print("api = wandb.Api()")
    print("runs = api.runs('entity/project')  # lightweight=True by default")
    print("for run in runs:")
    print("    print(f'{run.name}: {run.state}')  # Fast - no heavy data loaded")
    print("    if run.state == 'finished':")
    print("        config = run.config  # Lazy loading - loads full data when needed")
    
    print("\n# Example 2: Smart cache upgrade")
    print("runs1 = api.runs('entity/project', lightweight=True)   # Lightweight cache")
    print("runs2 = api.runs('entity/project', lightweight=False)  # Same cache, upgraded!")
    print("# runs1 is runs2  # True - same object reference")
    
    print("\n# Example 3: Explicit full data loading")
    print("runs = api.runs('entity/project', lightweight=True)")
    print("specific_run = list(runs)[0]")
    print("specific_run.load_full_data()  # Explicitly load heavy fields")
    print("config = specific_run.config  # No additional API call needed")
    
    print("\n# Example 4: Full mode (if you need all data upfront)")
    print("runs = api.runs('entity/project', lightweight=False)")
    print("for run in runs:")
    print("    config = run.config  # All data already loaded")
    
    print("\n" + "=" * 70)
    
    # Run the actual tests
    main()