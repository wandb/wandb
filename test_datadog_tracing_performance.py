#!/usr/bin/env python
"""
Performance test comparing lightweight vs full mode with Datadog tracing enabled
Uses X-Wandb-Force-Trace=true header to track GraphQL performance differences
"""

import sys
import os
import time
import tracemalloc
import gc
import json
from typing import Optional

# Add current directory to path to use local wandb
sys.path.insert(0, '/Users/thanos/work/repos/sdk-dev/wandb')

print("🔍 Light Runs Fragment Performance Test with Datadog Tracing")
print("=" * 70)

def patch_client_for_tracing(client):
    """Patch the GraphQL client to include Datadog tracing headers"""
    # Patch the underlying transport's session to add headers
    if hasattr(client, '_client') and hasattr(client._client, 'transport'):
        transport = client._client.transport
        if hasattr(transport, 'session'):
            # Add persistent headers to the session
            if not hasattr(transport.session, 'headers'):
                transport.session.headers = {}
            transport.session.headers['X-Wandb-Force-Trace'] = 'true'
            print("✅ Added X-Wandb-Force-Trace header to GraphQL session")
    
    # Also patch the execute method for logging
    original_execute = client.execute
    
    def execute_with_logging(*args, **kwargs):
        print(f"🔍 GraphQL Request (with X-Wandb-Force-Trace: true)")
        start_time = time.time()
        
        try:
            result = original_execute(*args, **kwargs)
            duration = time.time() - start_time
            print(f"   ⏱️  Request completed in: {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            print(f"   ❌ Request failed after: {duration:.3f}s - {e}")
            raise
    
    client.execute = execute_with_logging
    return client

def measure_performance(func, description: str):
    """Measure execution time and memory usage"""
    print(f"\n🧪 Testing: {description}")
    print("-" * 50)
    
    gc.collect()
    tracemalloc.start()
    start_time = time.time()
    
    try:
        result = func()
    finally:
        end_time = time.time()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    
    duration = end_time - start_time
    peak_mb = peak / 1024 / 1024
    
    print(f"✅ Result: {duration:.2f}s, Peak Memory: {peak_mb:.1f}MB")
    return result, duration, peak_mb

def test_lightweight_mode(api, project: str, limit: int = 50):
    """Test lightweight mode performance"""
    
    def run_test():
        print("   📡 Creating runs iterator with lightweight=True")
        runs = api.runs(project, lightweight=True, per_page=25)
        
        count = 0
        print("   🔄 Iterating through runs (accessing basic fields only)")
        for run in runs:
            count += 1
            # Access only basic fields available in lightweight mode
            basic_info = {
                'id': run.id,
                'name': run.name, 
                'state': run.state,
                'created_at': run.created_at,
                'group': run.group
            }
            
            if count >= limit:
                break
        
        print(f"   ✅ Processed {count} runs")
        return count, basic_info
    
    return measure_performance(run_test, "Lightweight Mode (Basic Fields Only)")

def test_full_mode(api, project: str, limit: int = 50):
    """Test full mode performance"""
    
    def run_test():
        print("   📡 Creating runs iterator with lightweight=False")
        runs = api.runs(project, lightweight=False, per_page=25)
        
        count = 0
        print("   🔄 Iterating through runs (full data loaded upfront)")
        for run in runs:
            count += 1
            # Access the same basic fields, but full data is preloaded
            basic_info = {
                'id': run.id,
                'name': run.name,
                'state': run.state, 
                'created_at': run.created_at,
                'group': run.group
            }
            
            if count >= limit:
                break
        
        print(f"   ✅ Processed {count} runs")
        return count, basic_info
    
    return measure_performance(run_test, "Full Mode (All Data Preloaded)")

def test_heavy_data_access(api, project: str, limit: int = 30):
    """Test accessing heavy data in lightweight mode"""
    
    def run_test():
        print("   📡 Creating runs iterator with lightweight=True")
        runs = api.runs(project, lightweight=True, per_page=25)
        
        count = 0
        config_count = 0
        summary_count = 0
        
        print("   🔄 Accessing heavy data (config, summary) - triggers lazy loading")
        for run in runs:
            count += 1
            
            # Access basic fields first
            _ = run.id, run.name, run.state
            
            # Access heavy data - this will trigger additional GraphQL requests
            try:
                config = run.config
                if config:
                    config_count += 1
                    print(f"     🔍 Loaded config for run {run.id}")
                
                summary = run.summary
                if summary:
                    summary_count += 1
                    print(f"     📊 Loaded summary for run {run.id}")
                    
            except Exception as e:
                print(f"     ⚠️  Could not load data for run {run.id}: {e}")
            
            if count >= limit:
                break
        
        print(f"   ✅ Processed {count} runs, {config_count} configs, {summary_count} summaries")
        return count, config_count, summary_count
    
    return measure_performance(run_test, "Heavy Data Access (Lazy Loading)")

def test_selective_loading(api, project: str, limit: int = 50):
    """Test selective loading pattern"""
    
    def run_test():
        print("   📡 Creating runs iterator with lightweight=True")
        runs = api.runs(project, lightweight=True, per_page=25)
        
        count = 0
        loaded_count = 0
        
        print("   🎯 Selective loading: only load heavy data for finished runs")
        for run in runs:
            count += 1
            
            # Fast filtering using lightweight fields
            _ = run.id, run.name, run.state
            
            # Only load heavy data for finished runs (selective)
            if run.state == "finished" and count % 5 == 0:  # Every 5th finished run
                try:
                    print(f"     🔄 Loading full data for finished run {run.id}")
                    if hasattr(run, 'load_full_data'):
                        run.load_full_data()
                    config = run.config
                    summary = run.summary
                    if config or summary:
                        loaded_count += 1
                        print(f"     ✅ Loaded full data for run {run.id}")
                except Exception as e:
                    print(f"     ⚠️  Could not load data for run {run.id}: {e}")
            
            if count >= limit:
                break
        
        print(f"   ✅ Processed {count} runs, {loaded_count} with full data")
        return count, loaded_count
    
    return measure_performance(run_test, "Selective Loading Pattern")

def main():
    """Main test execution"""
    project = "wandb/large_runs_demo"
    limit = 50
    
    print(f"Project: {project}")
    print(f"Run limit: {limit}")
    print(f"Datadog Tracing: ✅ ENABLED")
    print("\nDatadog Query: env:prod @wandb.force_trace:true")
    
    try:
        import wandb
        api = wandb.Api()
        
        # Enable Datadog tracing by patching the client execute method
        patch_client_for_tracing(api.client)
        
        print(f"\n🔗 Connected as: {api.viewer.username}")
        
        # Test 1: Lightweight Mode
        (count1, info1), time1, mem1 = test_lightweight_mode(api, project, limit)
        
        # Test 2: Full Mode  
        (count2, info2), time2, mem2 = test_full_mode(api, project, limit)
        
        # Test 3: Heavy Data Access
        (count3, configs, summaries), time3, mem3 = test_heavy_data_access(api, project, 30)
        
        # Test 4: Selective Loading
        (count4, loaded), time4, mem4 = test_selective_loading(api, project, limit)
        
        # Performance Comparison
        print(f"\n📊 PERFORMANCE COMPARISON")
        print("=" * 70)
        print(f"{'Test':<25} | {'Time':<8} | {'Memory':<10} | {'Improvement'}")
        print("-" * 70)
        print(f"{'Lightweight Mode':<25} | {time1:8.2f}s | {mem1:8.1f}MB | Baseline")
        print(f"{'Full Mode':<25} | {time2:8.2f}s | {mem2:8.1f}MB | {time1/time2 if time2 > 0 else 0:.1f}x faster")
        print(f"{'Heavy Data Access':<25} | {time3:8.2f}s | {mem3:8.1f}MB | {time1/time3 if time3 > 0 else 0:.1f}x vs LW")
        print(f"{'Selective Loading':<25} | {time4:8.2f}s | {mem4:8.1f}MB | {time1/time4 if time4 > 0 else 0:.1f}x vs LW")
        
        # Memory Comparison
        if mem2 > 0:
            memory_reduction = ((mem2 - mem1) / mem2 * 100)
            print(f"\n💾 MEMORY EFFICIENCY:")
            print(f"   Lightweight vs Full: {memory_reduction:.1f}% less memory")
        
        # Datadog Information
        print(f"\n🔍 DATADOG TRACING ANALYSIS:")
        print("=" * 70)
        print("✅ All GraphQL requests include 'X-Wandb-Force-Trace: true' header")
        print("📊 Check Datadog with query: env:prod @wandb.force_trace:true")
        print("🎯 Look for performance differences in:")
        print("   - GraphQL query execution time") 
        print("   - Fragment processing time")
        print("   - JSON serialization/parsing time")
        print("   - Network transfer differences")
        
        # Fragment Information
        print(f"\n🧬 FRAGMENT ANALYSIS:")
        print("=" * 70)
        print("LIGHTWEIGHT_RUN_FRAGMENT excludes:")
        print("   ❌ config (JSON config data)")
        print("   ❌ systemMetrics (System monitoring data)")  
        print("   ❌ summaryMetrics (All logged metrics)")
        print("   ❌ historyKeys (History metadata)")
        print("\nRUN_FRAGMENT includes:")
        print("   ✅ All lightweight fields +")
        print("   ✅ config, systemMetrics, summaryMetrics, historyKeys")
        
        print(f"\n🎉 Test completed successfully!")
        print(f"   Total GraphQL requests made with tracing enabled")
        print(f"   Check Datadog for performance insights")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 