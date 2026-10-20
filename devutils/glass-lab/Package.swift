// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ArciumGlassLab",
    platforms: [.macOS("26.0")],
    targets: [
        .target(name: "GlassNative", path: "Sources/GlassNative", publicHeadersPath: "include",
                cxxSettings: [.unsafeFlags(["-fobjc-arc"])],
                linkerSettings: [.linkedFramework("AppKit"), .linkedFramework("QuartzCore")]),
        .executableTarget(name: "ArciumGlassLab", dependencies: ["GlassNative"], exclude: ["Resources"]),
        .testTarget(name: "GlassLabTests", dependencies: ["ArciumGlassLab"])
    ],
    cxxLanguageStandard: .cxx20
)
