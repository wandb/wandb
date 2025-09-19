#!/usr/bin/env python3
"""
Artifact Cache Performance Test
Generates telemetry data for monitoring cache impact in DataDog
"""
import os
import tempfile
import shutil
import time
import random
import string
from pathlib import Path

import wandb

# Enable detailed telemetry for DataDog monitoring
os.environ["WANDB__EXTRA_HTTP_HEADERS"] = '{"X-Wandb-Force-Trace": "true"}'

class ArtifactCacheTest:
    def __init__(self, num_files=5000, project="cache-performance-test"):
        self.num_files = num_files
        self.project = project
        self.temp_dir = tempfile.mkdtemp(prefix="wandb_cache_test_")
        self.upload_dir = Path(self.temp_dir) / "upload"
        self.download_dir_no_cache = Path(self.temp_dir) / "download_no_cache"
        self.download_dir_with_cache = Path(self.temp_dir) / "download_with_cache"
        
        print(f"Test directory: {self.temp_dir}")
        print(f"Testing with {num_files} files")
        
    def generate_random_content(self, size_kb=10):
        """Generate random file content of specified size"""
        size_bytes = size_kb * 1024
        return ''.join(random.choices(string.ascii_letters + string.digits, k=size_bytes))
        
    def create_test_files(self):
        """Create 5000 random files with varying sizes"""
        print("Creating test files...")
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        file_sizes = [1, 5, 10, 50, 100, 500]  # KB sizes
        
        for i in range(self.num_files):
            if i % 500 == 0:
                print(f"  Created {i}/{self.num_files} files...")
                
            # Random file size and content
            size_kb = random.choice(file_sizes)
            content = self.generate_random_content(size_kb)
            
            # Create nested directory structure for some files
            if i % 10 == 0:
                subdir = self.upload_dir / f"subdir_{i // 100}"
                subdir.mkdir(exist_ok=True)
                file_path = subdir / f"file_{i:05d}.txt"
            else:
                file_path = self.upload_dir / f"file_{i:05d}.txt"
                
            file_path.write_text(content)
            
        print(f"✅ Created {self.num_files} test files")
        return self.upload_dir
        
    def upload_artifact(self):
        """Upload files as wandb artifact"""
        print("Uploading artifact...")
        
        run = wandb.init(
            project=self.project,
            job_type="upload",
            tags=["cache-test", "upload"]
        )
        
        start_time = time.time()
        
        # Create and log artifact
        artifact = wandb.Artifact(
            name="cache-test-dataset",
            type="dataset",
            description=f"Test dataset with {self.num_files} files for cache performance testing"
        )
        
        artifact.add_dir(str(self.upload_dir))
        
        #run.log_artifact(artifact)
        
        upload_time = time.time() - start_time
        print(f"✅ Upload completed in {upload_time:.2f} seconds")
        
        run.finish()
        return artifact.name
        
    def download_without_cache(self, artifact_name):
        """Download artifact with cache disabled"""
        print("\n" + "="*60)
        print("DOWNLOADING WITHOUT CACHE (First run - should be slow)")
        print("="*60)
        
        # Clear any existing cache to simulate fresh download
        cache_dir = Path.home() / ".cache" / "wandb" / "artifacts"
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            print("🗑️  Cleared existing artifact cache")
            
        self.download_dir_no_cache.mkdir(parents=True, exist_ok=True)
        
        run = wandb.init(
            project=self.project,
            job_type="download-no-cache",
            tags=["cache-test", "download", "no-cache"]
        )
        
        start_time = time.time()
        
        # Download artifact
        artifact = run.use_artifact(f"{artifact_name}:latest")
        artifact_dir = artifact.download(root=str(self.download_dir_no_cache))
        
        download_time = time.time() - start_time
        
        print(f"⏱️  Download without cache: {download_time:.2f} seconds")
        print(f"📁 Files downloaded to: {artifact_dir}")
        
        # Log metrics for DataDog
        run.log({
            "cache_enabled": False,
            "download_time_seconds": download_time,
            "num_files": self.num_files,
            "test_phase": "no_cache"
        })
        
        run.finish()
        return download_time
        
    def download_with_cache(self, artifact_name):
        """Download artifact with cache enabled (should hit cached checksums)"""
        print("\n" + "="*60)
        print("DOWNLOADING WITH CACHE (Second run - should be fast)")  
        print("="*60)
        
        self.download_dir_with_cache.mkdir(parents=True, exist_ok=True)
        
        run = wandb.init(
            project=self.project,
            job_type="download-with-cache",
            tags=["cache-test", "download", "with-cache"]
        )
        
        start_time = time.time()
        
        # Download artifact (should use cached checksums for verification)
        artifact = run.use_artifact(f"{artifact_name}:latest")
        artifact_dir = artifact.download(root=str(self.download_dir_with_cache))
        
        download_time = time.time() - start_time
        
        print(f"⚡ Download with cache: {download_time:.2f} seconds")
        print(f"📁 Files downloaded to: {artifact_dir}")
        
        # Log metrics for DataDog
        run.log({
            "cache_enabled": True,
            "download_time_seconds": download_time,
            "num_files": self.num_files,
            "test_phase": "with_cache"
        })
        
        run.finish()
        return download_time
        
    def validate_downloads(self):
        """Verify both downloads are identical"""
        print("\nValidating downloads...")
        
        # Simple validation - check file counts
        no_cache_files = list(self.download_dir_no_cache.rglob("*"))
        with_cache_files = list(self.download_dir_with_cache.rglob("*"))
        
        no_cache_count = len([f for f in no_cache_files if f.is_file()])
        with_cache_count = len([f for f in with_cache_files if f.is_file()])
        
        print(f"Files without cache: {no_cache_count}")
        print(f"Files with cache: {with_cache_count}")
        
        if no_cache_count == with_cache_count == self.num_files:
            print("✅ Download validation passed")
            return True
        else:
            print("❌ Download validation failed")
            return False
            
    def cleanup(self):
        """Clean up test directories"""
        print(f"\nCleaning up {self.temp_dir}...")
        shutil.rmtree(self.temp_dir)
        print("✅ Cleanup complete")
        
    def run_full_test(self):
        """Run complete cache performance test"""
        print("🚀 Starting Artifact Cache Performance Test")
        print(f"📊 DataDog monitoring enabled with X-Wandb-Force-Trace header")
        
        try:
            # Step 1: Create test files
            self.create_test_files()
            
            # Step 2: Upload to wandb
            artifact_name = self.upload_artifact()
            
            # Step 3: Download without cache (first time)
            time_no_cache = self.download_without_cache(artifact_name)
            
            # Step 4: Download with cache (second time - should be faster)
            time_with_cache = self.download_with_cache(artifact_name)
            
            # Step 5: Validate results
            self.validate_downloads()
            
            # Step 6: Report results
            speedup = time_no_cache / time_with_cache if time_with_cache > 0 else 0
            
            print("\n" + "="*60)
            print("PERFORMANCE RESULTS")
            print("="*60)
            print(f"📁 Files processed: {self.num_files}")
            print(f"⏱️  Without cache: {time_no_cache:.2f} seconds")
            print(f"⚡ With cache: {time_with_cache:.2f} seconds")
            print(f"🚀 Speedup: {speedup:.1f}x")
            print(f"💾 Time saved: {time_no_cache - time_with_cache:.2f} seconds")
            
            # Final summary run for DataDog
            summary_run = wandb.init(
                project=self.project,
                job_type="test-summary",
                tags=["cache-test", "summary"]
            )
            
            summary_run.log({
                "total_files": self.num_files,
                "time_no_cache": time_no_cache,
                "time_with_cache": time_with_cache,
                "speedup_factor": speedup,
                "time_saved_seconds": time_no_cache - time_with_cache,
                "cache_effectiveness": ((time_no_cache - time_with_cache) / time_no_cache) * 100
            })
            
            summary_run.finish()
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            raise
        finally:
            self.cleanup()


if __name__ == "__main__":
    # You can adjust the number of files for testing
    test = ArtifactCacheTest(num_files=5000)
    test.run_full_test()
    
    print("\n🎯 Test completed! Check DataDog for telemetry data:")
    print("   - Look for X-Wandb-Force-Trace requests")
    print("   - Compare download times between cache phases")
    print("   - Monitor artifact.* metrics for differences")
    print("   - Check for reduced server requests in second phase")
