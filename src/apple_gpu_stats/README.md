This builds a universal binary for MacOS GPU monitoring on Arm processors.

## Building

Install xcode, make sure your command line is using the official Xcode app:

```
xcode-select -switch ~/Application/Xcode.app
```

You'll need to be a member of the W&B Apple Developer account, reachout to vanpelt@wandb.com.

Run `xcodebuild build` to build the binary, then copy the binary into vendor with:

`cp build/Release/apple_gpu_stats ../wandb/bin/`