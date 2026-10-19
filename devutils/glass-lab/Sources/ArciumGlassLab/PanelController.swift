import AppKit
import SwiftUI
import GlassNative

@MainActor
private final class ControlTile: NSView {
    let native = LabCreateMaterialView()!
    let solid = NSView()
    let image = NSImageView()
    let tone = NSView()
    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        for view in [solid, native, image, tone] {
            addSubview(view)
            view.wantsLayer = true
            view.layer?.cornerRadius = 20
            view.layer?.masksToBounds = true
        }
        image.imageScaling = .scaleAxesIndependently
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func update(recipe: Recipe, tint: RGB, dark: Bool) {
        for view in [solid, native, image, tone] { view.frame = bounds }
        let alpha = recipe.effectiveTint
        solid.layer?.backgroundColor = NSColor(recipe.solidColor(dark: dark, tint: tint).color).cgColor
        let base = Recipe.baseColor(dark: dark)
        tone.layer?.backgroundColor = NSColor(srgbRed: base.red, green: base.green, blue: base.blue, alpha: recipe.intensity).cgColor
        solid.isHidden = recipe.material != .solid
        native.isHidden = recipe.material == .solid || recipe.material == .glassmorphic
        image.isHidden = recipe.material != .glassmorphic
        if !native.isHidden { LabApplyMaterial(native, recipe.material.nativeCode, tint.red, tint.green, tint.blue, alpha, 20) }
        layer?.shadowColor = NSColor.black.cgColor
        layer?.shadowOpacity = recipe.shadow ? 0.3 : 0
        layer?.shadowRadius = 4
        layer?.shadowOffset = CGSize(width: 0, height: -2)
        layer?.shadowPath = CGPath(ellipseIn: bounds, transform: nil)
    }
}

@MainActor
final class PanelController {
    let store: LabStore
    let panel: LabHostPanel
    private let native = LabCreateMaterialView()!
    private let shaderView = NSImageView()
    private let solid = NSView()
    private let tone = NSView()
    private let container = NSView()
    private let foreground: NSHostingView<PanelContent>
    private let shader = ShaderRenderer()
    private let controlTiles = (0..<5).map { _ in ControlTile(frame: .zero) }
    weak var anchor: NSView?
    private var lastShaderKey = ""
    private var shaderGeometry: (size: CGSize, rect: CGRect)?

    init(store: LabStore) {
        self.store = store
        panel = LabHostPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
        panel.hidesOnDeactivate = false; panel.becomesKeyOnlyIfNeeded = true
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.fullScreenAuxiliary]
        foreground = NSHostingView(rootView: PanelContent(store: store, recipe: store.displayedRecipe))
        foreground.sizingOptions = []; foreground.safeAreaRegions = []
        let root = NSView(); root.wantsLayer = true; panel.contentView = root
        root.addSubview(container)
        container.wantsLayer = true
        for view in [solid, native, shaderView, tone, foreground] { container.addSubview(view) }
        for tile in controlTiles { container.addSubview(tile, positioned: .below, relativeTo: foreground) }
        solid.wantsLayer = true; shaderView.imageScaling = .scaleAxesIndependently
    }

    func refresh() {
        guard let anchor, let parent = anchor.window else { return }
        let size = anchor.bounds.size
        guard size.width > 100, size.height > 100 else { return }
        let recipe = store.displayedRecipe
        let controls = store.document.preview == .controls
        let surfaceSize: CGSize
        switch store.document.preview {
        case .command: surfaceSize = CGSize(width: min(760, size.width-56), height: 336)
        case .mru: surfaceSize = CGSize(width: min(770, size.width-56), height: 218)
        case .peek: surfaceSize = CGSize(width: min(590, size.width-56), height: min(580, size.height-80))
        case .controls: surfaceSize = CGSize(width: 350, height: 70)
        case .window: surfaceSize = CGSize(width: min(830, size.width-56), height: min(590, size.height-80))
        }
        let rect = CGRect(x: (size.width-surfaceSize.width)/2, y: (size.height-surfaceSize.height)/2, width: surfaceSize.width, height: surfaceSize.height)
        shaderGeometry = (size, rect)
        let screen = parent.convertToScreen(anchor.convert(rect.insetBy(dx: -22, dy: -22), to: nil))
        panel.setFrame(screen, display: true)
        container.frame = CGRect(origin: CGPoint(x: 22, y: 22), size: surfaceSize)
        for view in [solid, native, shaderView, tone, foreground] { view.frame = container.bounds }
        let tint = recipe.windowTint ? store.document.windowColor : recipe.tintColor
        let effective = recipe.effectiveTint
        solid.layer?.backgroundColor = NSColor(recipe.solidColor(dark: store.document.dark, tint: tint).color).cgColor
        let base = Recipe.baseColor(dark: store.document.dark)
        tone.wantsLayer = true
        tone.layer?.backgroundColor = NSColor(srgbRed: base.red, green: base.green, blue: base.blue, alpha: recipe.intensity).cgColor
        tone.isHidden = controls
        for view in [solid, native, shaderView, tone] {
            view.wantsLayer = true
            view.layer?.cornerRadius = recipe.radius
            view.layer?.cornerCurve = .continuous
            view.layer?.masksToBounds = true
        }
        container.layer?.shadowColor = NSColor.black.cgColor
        container.layer?.shadowOpacity = recipe.shadow && !controls ? 0.35 : 0
        container.layer?.shadowRadius = 12
        container.layer?.shadowOffset = CGSize(width: 0, height: -5)
        container.layer?.shadowPath = CGPath(roundedRect: container.bounds, cornerWidth: recipe.radius, cornerHeight: recipe.radius, transform: nil)
        solid.isHidden = controls || recipe.material != .solid
        native.isHidden = controls || recipe.material == .solid || recipe.material == .glassmorphic
        shaderView.isHidden = controls || recipe.material != .glassmorphic
        panel.appearance = NSAppearance(named: store.document.dark ? .darkAqua : .aqua)
        native.appearance = recipe.material == .systemLiquid ? panel.appearance : nil
        var forced = store.activeAppearance
        if forced == 0 { forced = recipe.material == .liquid ? 1 : recipe.material == .frosted ? 2 : 0 }
        LabSetWindowAppearance(panel, Int32(forced))
        if !native.isHidden {
            LabApplyMaterial(native, recipe.material.nativeCode, tint.red, tint.green, tint.blue, effective, recipe.radius)
        }
        for (index, tile) in controlTiles.enumerated() {
            tile.isHidden = !controls
            guard controls else { continue }
            let tileRect = CGRect(x: 23+Double(index)*66, y: 15, width: 40, height: 40)
            tile.frame = tileRect
            tile.update(recipe: recipe, tint: tint, dark: store.document.dark)
            tile.native.appearance = recipe.material == .systemLiquid ? panel.appearance : nil
        }
        renderAnimationFrame()
        foreground.rootView = PanelContent(store: store, recipe: recipe)
        if store.panelVisible {
            if panel.parent !== parent { parent.addChildWindow(panel, ordered: .above) }
            panel.orderFront(nil)
        } else { panel.orderOut(nil) }
    }
    func renderAnimationFrame() {
        guard store.panelVisible, store.displayedRecipe.material == .glassmorphic,
              let geometry = shaderGeometry else { return }
        let recipe = store.displayedRecipe
        let phase = store.phase
        let key = String(describing: store.sceneDocument) + String(describing: geometry.size) + String(phase)
        guard key != lastShaderKey else { return }
        if store.document.preview == .controls {
            for tile in controlTiles {
                var circle = recipe; circle.radius = 20
                tile.image.image = shader.render(document: store.sceneDocument, recipe: circle, stageSize: geometry.size,
                    panelRect: tile.frame.offsetBy(dx: geometry.rect.minX, dy: geometry.rect.minY), phase: phase)
                if tile.image.image == nil { tile.solid.isHidden = false; store.status = shader.error ?? "Shader rendering failed" }
            }
        } else {
            shaderView.image = shader.render(document: store.sceneDocument, recipe: recipe, stageSize: geometry.size,
                panelRect: geometry.rect, phase: phase)
            if shaderView.image == nil { solid.isHidden = false; store.status = shader.error ?? "Shader rendering failed" }
        }
        lastShaderKey = key
    }
    func close() {
        panel.parent?.removeChildWindow(panel)
        panel.orderOut(nil)
        panel.close()
    }
}

struct StageAnchor: NSViewRepresentable {
    var controller: PanelController
    func makeNSView(context: Context) -> AnchorView {
        let view = AnchorView()
        view.changed = { [weak controller, weak view] in
            controller?.anchor = view
            controller?.refresh()
        }
        controller.anchor = view
        return view
    }
    func updateNSView(_ view: AnchorView, context: Context) {}
    final class AnchorView: NSView {
        var changed: (() -> Void)?
        private var lastPlacement: NSRect?
        override func layout() {
            super.layout()
            let placement = convert(bounds, to: nil)
            guard placement != lastPlacement else { return }
            lastPlacement = placement
            changed?()
        }
        override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); DispatchQueue.main.async { [weak self] in self?.changed?() } }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
    }
}
