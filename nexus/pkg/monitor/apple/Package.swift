// swift-tools-version: 5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

// swift build -c release -Xswiftc -cross-module-optimization

import PackageDescription

let package = Package(
    name: "apple",
    platforms: [
        .macOS(.v10_14) // Set your minimum deployment target
    ],
    targets: [
        // Targets are the basic building blocks of a package, defining a module or a test suite.
        // Targets can depend on other targets in this package and products from dependencies.
        .executableTarget(
            name: "apple"),
        // .target(
        //     name: "apple",
        //     dependencies: []),
    ]
)
