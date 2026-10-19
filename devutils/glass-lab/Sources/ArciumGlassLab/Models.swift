import AppKit
import SwiftUI

enum Material: String, Codable, CaseIterable, Identifiable {
    case fast, liquid, systemLiquid, frosted, glassmorphic, solid
    var id: String { rawValue }
    var title: String {
        switch self {
        case .fast: "Fast"
        case .liquid: "Clear"
        case .systemLiquid: "Liquid"
        case .frosted: "Frosted"
        case .glassmorphic: "Chromium (glassmorphic)"
        case .solid: "Solid"
        }
    }
    var nativeCode: Int32 {
        switch self {
        case .solid: 0; case .fast: 1; case .liquid: 2
        case .systemLiquid: 3; case .frosted: 4; case .glassmorphic: 5
        }
    }
    var explanation: String {
        switch self {
        case .fast: "AppKit blur with a separate tint layer."
        case .liquid: "AppKit regular glass, variant 9, active appearance."
        case .systemLiquid: "Public SwiftUI Glass.regular and glassEffect."
        case .frosted: "AppKit clear glass, inactive appearance, no tint."
        case .glassmorphic: "Production shader equations in Metal. Chromium compositing is simulated."
        case .solid: "Tint over a dark or light neutral base, following page appearance."
        }
    }
}

enum Preview: String, Codable, CaseIterable, Identifiable {
    case command, mru, peek, controls, window
    var id: String { rawValue }
    var title: String {
        switch self {
        case .command: "Command bar"; case .mru: "Tab switcher"
        case .peek: "Peek"; case .controls: "Floating controls"; case .window: "Window chrome"
        }
    }
    var icon: String {
        switch self {
        case .command: "magnifyingglass"; case .mru: "rectangle.on.rectangle"
        case .peek: "rectangle.inset.filled"; case .controls: "slider.horizontal.3"
        case .window: "macwindow"
        }
    }
}

enum Backdrop: String, Codable, CaseIterable, Identifiable {
    case editorial, documentation, contrast
    var id: String { rawValue }
    var title: String {
        switch self { case .editorial: "Editorial"; case .documentation: "Documentation"; case .contrast: "Contrast test" }
    }
}

enum InkStyle: String, Codable, CaseIterable {
    case automatic = "Auto", light = "Light", dark = "Dark"
}

struct RGB: Codable, Equatable {
    var red: Double
    var green: Double
    var blue: Double
    init(_ hex: String) {
        let value = UInt32(hex.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0xB261E1
        red = Double((value >> 16) & 255) / 255
        green = Double((value >> 8) & 255) / 255
        blue = Double(value & 255) / 255
    }
    init(_ color: Color) {
        let c = NSColor(color).usingColorSpace(.sRGB) ?? .systemPurple
        red = c.redComponent; green = c.greenComponent; blue = c.blueComponent
        self = clamped()
    }
    var color: Color { Color(red: red, green: green, blue: blue) }
    var hex: String {
        let rgb = clamped()
        return String(format: "#%02X%02X%02X", Int((rgb.red*255).rounded()), Int((rgb.green*255).rounded()), Int((rgb.blue*255).rounded()))
    }
    func clamped() -> Self {
        var copy = self
        copy.red = red.isFinite ? min(1, max(0, red)) : 0
        copy.green = green.isFinite ? min(1, max(0, green)) : 0
        copy.blue = blue.isFinite ? min(1, max(0, blue)) : 0
        return copy
    }
    func mixed(with other: RGB, amount: Double) -> RGB {
        var result = self
        let alpha = min(1, max(0, amount))
        result.red = red*(1-alpha)+other.red*alpha
        result.green = green*(1-alpha)+other.green*alpha
        result.blue = blue*(1-alpha)+other.blue*alpha
        return result
    }
}

struct Recipe: Codable, Equatable {
    var material: Material = .systemLiquid
    var tint: Double = 0.30
    var tintColor = RGB("#B261E1")
    var accent = RGB("#C0DAFF")
    var windowTint = true
    var radius: Double = 12
    var shadow = true
    var blur: Double = 9
    var itemBacking: Double = 0.12
    var textShadow: Double = 0.45
    var textSize: Double = 15
    var ink: InkStyle?
    var neutralIntensity: Double?
    var edge: Double = 18
    var refraction: Double = 7
    var dispersion: Double = 0.15
    var specular: Double = 0.26
    var grain: Double = 0.008
    var scrimDim: Double = 0.28
    var scrimBlur: Double = 9
    var effectiveTint: Double { material == .frosted ? 0 : tint }
    var intensity: Double {
        guard let value = neutralIntensity, value.isFinite else { return 0 }
        return min(1, max(0, value))
    }
    static func baseColor(dark: Bool) -> RGB { RGB(dark ? "#1D1E1C" : "#F2F2F0") }
    func solidColor(dark: Bool, tint: RGB) -> RGB {
        Self.baseColor(dark: dark).mixed(with: tint, amount: effectiveTint)
    }
    func clamped() -> Self {
        var copy = self
        func bound(_ value: Double, _ range: ClosedRange<Double>, _ fallback: Double) -> Double {
            value.isFinite ? min(range.upperBound, max(range.lowerBound, value)) : fallback
        }
        copy.tint = bound(tint, 0...1, 0.3)
        copy.radius = bound(radius, 0...48, 12)
        copy.blur = bound(blur, 0...30, 9)
        copy.itemBacking = bound(itemBacking, 0...0.6, 0.12)
        copy.textShadow = bound(textShadow, 0...1, 0.45)
        copy.textSize = bound(textSize, 11...22, 15)
        if let neutralIntensity { copy.neutralIntensity = bound(neutralIntensity, 0...1, 0) }
        copy.edge = bound(edge, 1...80, 18)
        copy.refraction = bound(refraction, 0...40, 7)
        copy.dispersion = bound(dispersion, 0...1, 0.15)
        copy.specular = bound(specular, 0...1, 0.26)
        copy.grain = bound(grain, 0...0.1, 0.008)
        copy.scrimDim = bound(scrimDim, 0...0.8, 0.28)
        copy.scrimBlur = bound(scrimBlur, 0...30, 9)
        copy.tintColor = tintColor.clamped(); copy.accent = accent.clamped()
        return copy
    }
    func productionTuning(windowColor: RGB) -> [String: Any] {
        ["panelMaterial": material.rawValue, "panelTint": tint,
         "panelTintColor": windowTint ? "" : tintColor.hex,
         "panelBlur": blur, "panelShadow": shadow,
         "controlFinish": "glass", "controlTint": 0.55, "controlEdge": 0.38,
         "scrimDim": scrimDim, "scrimBlur": scrimBlur]
    }
}

struct LabDocument: Codable, Equatable {
    var version = 1
    var recipe = Recipe()
    var reference: Recipe?
    var preview: Preview = .command
    var backdrop: Backdrop = .editorial
    var dark = true
    var moving = false
    var windowColor = RGB("#B261E1")
}

@MainActor
final class LabStore: ObservableObject {
    @Published var document: LabDocument { didSet { save(); onChange?() } }
    @Published var status = ""
    @Published var selectedItem = 0
    @Published var panelVisible = true { didSet { onChange?() } }
    @Published var activeAppearance = 0 { didSet { onChange?() } }
    @Published var showingReference = false { didSet { onChange?() } }
    var onChange: (() -> Void)?
    private let defaults: UserDefaults
    private let key = "lab-document-v1"
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        document = defaults.data(forKey: key).flatMap { try? JSONDecoder().decode(LabDocument.self, from: $0) } ?? LabDocument()
        document.recipe = document.recipe.clamped()
        document.reference = document.reference?.clamped()
        document.windowColor = document.windowColor.clamped()
    }
    func save() {
        if let data = try? JSONEncoder().encode(document) { defaults.set(data, forKey: key) }
    }
    var resolvedTint: RGB { document.recipe.windowTint ? document.windowColor : document.recipe.tintColor }
    var displayedRecipe: Recipe { showingReference ? document.reference ?? document.recipe : document.recipe }
    var sceneDocument: LabDocument {
        var scene = document
        scene.recipe = displayedRecipe
        if displayedRecipe.material == .glassmorphic { scene.moving = false }
        return scene
    }
    func reset() { showingReference = false; document.recipe = Recipe(); status = "Material reset" }
    func pin() { document.reference = document.recipe; status = "Reference saved" }
    func swap() {
        guard let reference = document.reference else { return }
        let current = document.recipe
        document.recipe = reference; document.reference = current
    }
    func copyTuning() {
        do {
            let data = try JSONSerialization.data(withJSONObject: displayedRecipe.productionTuning(windowColor: document.windowColor), options: [.prettyPrinted, .sortedKeys])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(String(decoding: data, as: UTF8.self), forType: .string)
            status = "Browser tuning copied"
        } catch { status = error.localizedDescription }
    }
    func export() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "glass-recipe.json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(document).write(to: url, options: .atomic)
            status = "Recipe exported"
        } catch { status = "Could not export: \(error.localizedDescription)" }
    }
    func load() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            var value = try JSONDecoder().decode(LabDocument.self, from: Data(contentsOf: url))
            guard value.version == 1 else { status = "Unsupported recipe version"; return }
            value.recipe = value.recipe.clamped(); value.reference = value.reference?.clamped()
            value.windowColor = value.windowColor.clamped()
            showingReference = false
            document = value; panelVisible = true; status = "Recipe imported"
        } catch { status = "Could not import: \(error.localizedDescription)" }
    }
}
