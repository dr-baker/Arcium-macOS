import AppKit
import CoreImage
import SwiftUI

@MainActor
final class ShaderRenderer {
    private let context = CIContext(options: [.workingColorSpace: CGColorSpace(name: CGColorSpace.sRGB)!])
    private let kernel: CIKernel?
    private var cachedSceneKey = ""
    private var cachedScene: CIImage?
    let error: String?
    init() {
        do {
            guard let url = Bundle.main.url(forResource: "Glass", withExtension: "metallib") else {
                throw NSError(domain: "GlassLab", code: 1, userInfo: [NSLocalizedDescriptionKey: "Glass.metallib is missing. Rebuild with ./lab build."])
            }
            kernel = try CIKernel(functionName: "glassLab", fromMetalLibraryData: Data(contentsOf: url))
            error = nil
        } catch {
            kernel = nil; self.error = error.localizedDescription
        }
    }
    static func sigma(extraBlur: Double) -> Double { sqrt(0.6 * 10 * 10 + extraBlur * extraBlur) }
    func render(document: LabDocument, recipe: Recipe, stageSize: CGSize, panelRect: CGRect) -> NSImage? {
        guard let kernel else { return nil }
        let sceneKey = String(describing: document) + String(describing: stageSize)
        if sceneKey != cachedSceneKey {
            let renderer = ImageRenderer(content: StageScene(document: document).frame(width: stageSize.width, height: stageSize.height))
            renderer.scale = 1 // All shader distances use logical points, like the core inputs.
            guard let image = renderer.cgImage else { return nil }
            cachedScene = CIImage(cgImage: image).clampedToExtent()
            cachedSceneKey = sceneKey
        }
        guard let original = cachedScene else { return nil }
        let sigma = Self.sigma(extraBlur: recipe.blur)
        let backdrop = original.applyingFilter("CIGaussianBlur", parameters: [kCIInputRadiusKey: sigma])
        let softened = backdrop.clampedToExtent().applyingFilter("CIGaussianBlur", parameters: [kCIInputRadiusKey: sigma])
        let tint = recipe.windowTint ? document.windowColor : recipe.tintColor
        let arguments: [Any] = [backdrop, softened,
            CIVector(x: panelRect.minX, y: panelRect.minY),
            CIVector(x: panelRect.width, y: panelRect.height),
            recipe.radius, recipe.edge, recipe.refraction, recipe.dispersion,
            recipe.effectiveTint, CIVector(x: tint.red, y: tint.green, z: tint.blue), recipe.specular, recipe.grain]
        guard let output = kernel.apply(extent: panelRect, roiCallback: { _, rect in rect.insetBy(dx: -90, dy: -90) }, arguments: arguments),
              let cgImage = context.createCGImage(output, from: panelRect) else { return nil }
        return NSImage(cgImage: cgImage, size: panelRect.size)
    }
}
