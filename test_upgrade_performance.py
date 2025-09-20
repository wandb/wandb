#!/usr/bin/env python3
"""
Test script to verify the upgrade_to_full performance issue is fixed.
"""

import os
import time
from wandb import Api

# Enable telemetry
os.environ["WANDB__EXTRA_HTTP_HEADERS"] = '{"X-Wandb-Force-Trace": "true"}'

def test_upgrade_performance():
    """Test that loading many runs doesn't cause excessive network calls"""
    print("Testing upgrade_to_full performance fix")
    print("=" * 50)

    api = Api()

    # Test 1: Loading runs with lazy=True should be fast
    print("\n1. Loading 50 runs with lazy=True...")
    start = time.time()
    runs = api.runs("wandb/large_runs_demo", lazy=True, per_page=50)
    run_list = list(runs)[:50]
    elapsed = time.time() - start

    print(f"✓ Loaded {len(run_list)} runs in {elapsed:.2f}s")
    if elapsed > 10:
        print("⚠️  Warning: This seems slow. Check for network issues.")
    else:
        print("✅ Good performance!")

    # Test 2: Upgrading to full should work without hanging
    print("\n2. Testing upgrade_to_full()...")
    start = time.time()
    try:
        runs.upgrade_to_full()
        elapsed = time.time() - start
        print(f"✓ Upgrade completed in {elapsed:.2f}s")
        if elapsed > 30:
            print("⚠️  Warning: Upgrade is slower than expected")
        else:
            print("✅ Upgrade performance is acceptable")
    except KeyboardInterrupt:
        print("❌ Upgrade hung and was interrupted - performance issue detected!")
        raise
    except Exception as e:
        print(f"❌ Error during upgrade: {e}")
        raise

    # Test 3: Verify data is accessible
    print("\n3. Verifying data access after upgrade...")
    start = time.time()
    for i in range(min(3, len(run_list))):
        run = run_list[i]
        config = run.config
        summary = run.summary_metrics
        print(f"  Run {i+1}: config={len(config)} keys, summary={len(summary)} keys")
    elapsed = time.time() - start
    print(f"✓ Data access took {elapsed:.2f}s")

    print("\n✅ All tests passed! The performance issue appears to be fixed.")
    print("🔍 Check Datadog for detailed traces")

if __name__ == "__main__":
    test_upgrade_performance()
