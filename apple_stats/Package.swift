// swift-tools-version: 5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

// swift build -c release -Xswiftc -cross-module-optimization
// use --show-bin-path to find the binary

import PackageDescription

let package = Package(
    name: "apple",
    platforms: [
        .macOS(.v10_14) // Set your minimum deployment target
    ],
    products: [
        .executable(name: "AppleStats", targets: ["AppleStats"])
    ],
    targets: [
        // Targets are the basic building blocks of a package, defining a module or a test suite.
        // Targets can depend on other targets in this package and products from dependencies.
        .executableTarget(
            name: "AppleStats"
        ),
        // .target(
        //     name: "AppleStats",
        //     dependencies: []),
    ]
)
