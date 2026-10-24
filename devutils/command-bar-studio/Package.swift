// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "ArciumCommandBarStudio",
    platforms: [.macOS(.v26)],
    dependencies: [
        .package(path: ".build/ProductionSettings"),
        .package(path: "../glass-lab")
    ],
    targets: [
        .executableTarget(name: "ArciumCommandBarStudio", dependencies: [
            .product(name: "ArciumSettingsUI", package: "ProductionSettings"),
            .product(name: "GlassNative", package: "glass-lab")
        ]),
        .testTarget(name: "CommandBarStudioTests", dependencies: ["ArciumCommandBarStudio"])
    ],
    swiftLanguageModes: [.v5]
)
