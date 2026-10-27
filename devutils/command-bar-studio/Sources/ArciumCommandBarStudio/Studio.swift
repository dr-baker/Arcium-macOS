import AppKit
import ArciumSettingsUI
import GlassNative
import QuartzCore

@MainActor
final class FlippedView: NSView { override var isFlipped: Bool { true } }

@MainActor
final class StageView: NSView {
    var changed: (() -> Void)?
    var dark = true { didSet { needsDisplay = true } }
    override var isFlipped: Bool { true }
    override func layout() { super.layout(); changed?() }
    override func draw(_ dirtyRect: NSRect) {
        (dark ? NSColor(srgbRed: 0.13, green: 0.15, blue: 0.18, alpha: 1) : NSColor(srgbRed: 0.89, green: 0.91, blue: 0.94, alpha: 1)).setFill(); bounds.fill()
        let ink = dark ? NSColor.white : NSColor.black
        func label(_ s: String, x: CGFloat, y: CGFloat, size: CGFloat, alpha: CGFloat = 1) {
            (s as NSString).draw(at: CGPoint(x: x, y: y), withAttributes: [.font: NSFont.systemFont(ofSize: size, weight: .medium), .foregroundColor: ink.withAlphaComponent(alpha)])
        }
        label("Today", x: 34, y: 35, size: 28)
        label("A little space to think.", x: 35, y: 78, size: 14, alpha: 0.5)
        let colors: [NSColor] = [.systemPurple, .systemBlue, .systemOrange]
        for i in 0..<3 {
            let x = CGFloat(i) * (bounds.width - 88) / 3 + 34
            colors[i].withAlphaComponent(dark ? 0.3 : 0.15).setFill()
            NSBezierPath(roundedRect: CGRect(x: x, y: 135, width: (bounds.width - 112) / 3, height: bounds.height - 215), xRadius: 18, yRadius: 18).fill()
            label(["Projects", "Reading", "Ideas"][i], x: x + 16, y: 153, size: 14, alpha: 0.7)
            for row in 0..<6 {
                ink.withAlphaComponent(0.06).setFill()
                NSBezierPath(roundedRect: CGRect(x: x + 14, y: 198 + CGFloat(row) * 53, width: (bounds.width - 112) / 3 - 28, height: 36), xRadius: 6, yRadius: 6).fill()
            }
        }
        label("Example workspace", x: 34, y: bounds.height - 48, size: 12, alpha: 0.4)
    }
}

@MainActor
final class StudioPanel {
    let panel = LabHostPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    let preview = CommandPreview(frame: .zero)
    private let material = LabCreateMaterialView()!
    private let root = FlippedView(), surface = FlippedView()
    private let mask = CAShapeLayer()
    weak var stage: StageView?
    private var pending: DispatchWorkItem?
    private var height: CGFloat = 0
    var dark = true { didSet { applyMaterial(); preview.dark = dark } }
    init() {
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
        panel.hidesOnDeactivate = false; panel.becomesKeyOnlyIfNeeded = true; panel.isReleasedWhenClosed = false
        panel.contentView = root
        root.wantsLayer = true; surface.wantsLayer = true
        root.addSubview(surface); surface.addSubview(material); surface.addSubview(preview)
        surface.autoresizingMask = [.width, .height]
        material.autoresizingMask = [.width, .height]; preview.autoresizingMask = [.width, .height]
        surface.layer?.mask = mask
        root.layer?.shadowColor = NSColor.black.cgColor; root.layer?.shadowOpacity = 0.35
        root.layer?.shadowRadius = 14; root.layer?.shadowOffset = CGSize(width: 0, height: -4)
        preview.onContourChange = { [weak self] path in
            guard let self else { return }
            CATransaction.begin(); CATransaction.setDisableActions(true)
            self.mask.frame = self.surface.bounds
            // The flipped AppKit backing view already supplies the transform.
            self.mask.path = path
            CATransaction.commit()
        }
        preview.onHeightChange = { [weak self] in self?.scheduleHeight() }
    }
    func applyMaterial() {
        panel.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        material.appearance = panel.appearance
        LabApplyMaterial(material, 3, 0.79, 0.71, 0.48, 0.05, 13)
        LabSetWindowAppearance(panel, 0)
    }
    private func scheduleHeight() {
        pending?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            let target = self.preview.desiredHeight
            let shrink = target < self.height
            self.height = target; self.place(animate: shrink)
        }
        pending = work
        DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(40), execute: work)
    }
    func place(animate: Bool = false) {
        guard let stage, let parent = stage.window else { return }
        if height == 0 { height = preview.desiredHeight }
        let size = CGSize(width: max(240, min(700, stage.bounds.width - 48)), height: min(height, stage.bounds.height - 72))
        let rect = CGRect(x: (stage.bounds.width - size.width) / 2, y: 65, width: size.width, height: size.height)
        let frame = parent.convertToScreen(stage.convert(rect.insetBy(dx: -22, dy: -22), to: nil))
        if animate {
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.06; context.timingFunction = CAMediaTimingFunction(name: .easeOut)
                panel.animator().setFrame(frame, display: true)
            }
        } else { panel.setFrame(frame, display: true) }
        surface.frame = CGRect(origin: CGPoint(x: 22, y: 22), size: size)
        material.frame = surface.bounds; preview.frame = surface.bounds
        preview.needsLayout = true; preview.layoutSubtreeIfNeeded()
        if panel.parent !== parent { parent.addChildWindow(panel, ordered: .above) }
        panel.orderFront(nil)
    }
    func close() { pending?.cancel(); panel.parent?.removeChildWindow(panel); panel.close() }
}

@MainActor
final class StudioRoot: NSView {
    let stage = StageView(), bar = NSView()
    var editor: NSView?
    var buttons: [NSView] = []
    override var isFlipped: Bool { true }
    override func layout() {
        super.layout()
        bar.frame = CGRect(x: 0, y: 0, width: bounds.width, height: 48)
        editor?.frame = CGRect(x: 0, y: 48, width: 520, height: bounds.height - 48)
        stage.frame = CGRect(x: 520, y: 48, width: bounds.width - 520, height: bounds.height - 48)
        var x: CGFloat = 18
        for button in buttons { button.frame = CGRect(x: x, y: 10, width: button.fittingSize.width + 10, height: 28); x += button.frame.width + 10 }
        stage.changed?()
    }
}

@MainActor
final class StudioApp: NSObject, NSApplicationDelegate, NSWindowDelegate, ArciumSettingsUIDelegate {
    private var window: NSWindow!
    private var controls: ArciumSettingsUIController!
    private var editor: NSViewController!
    private let root = StudioRoot(), panel = StudioPanel()
    private let preferences = UserDefaults.standard
    private var configuration = Configuration()
    private var dark = true
    private var snapshotPending = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let saved = preferences.dictionary(forKey: "configuration") { configuration = Configuration(saved) }
        dark = preferences.object(forKey: "dark") as? Bool ?? true
        controls = ArciumSettingsUIController(snapshot: snapshot(), delegate: self)
        editor = controls.makeCommandBarEditor(previewAvailable: true)
        root.editor = editor.view; root.addSubview(editor.view); root.addSubview(root.stage); root.addSubview(root.bar)
        for (title, action) in [("Light / Dark", #selector(toggleAppearance)), ("Reset examples", #selector(resetExamples)), ("Reset settings", #selector(resetSettings)), ("Copy configuration", #selector(copyConfiguration))] {
            let button = NSButton(title: title, target: self, action: action)
            button.bezelStyle = .rounded; button.bezelColor = .controlBackgroundColor
            button.contentTintColor = .labelColor
            root.bar.addSubview(button); root.buttons.append(button)
        }
        let screen = NSScreen.main?.visibleFrame ?? CGRect(x: 0, y: 0, width: 1440, height: 900)
        window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: min(1380, screen.width - 40), height: min(820, screen.height - 50)), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Command Bar Studio"
        window.minSize = CGSize(width: 1100, height: 700)
        window.isReleasedWhenClosed = false; window.delegate = self
        window.contentView = root; window.center()
        panel.stage = root.stage; root.stage.changed = { [weak self] in self?.panel.place() }
        panel.preview.configuration = configuration
        applyAppearance()
        installMenu()
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        root.layoutSubtreeIfNeeded(); panel.place(); panel.preview.focusSearch()
        if let index = CommandLine.arguments.firstIndex(of: "--ready-file"), CommandLine.arguments.indices.contains(index + 1) {
            let data = try? JSONSerialization.data(withJSONObject: ["pid": ProcessInfo.processInfo.processIdentifier, "bundle": Bundle.main.bundlePath])
            try? data?.write(to: URL(fileURLWithPath: CommandLine.arguments[index + 1]), options: .atomic)
        }
    }
    private func snapshot() -> NSDictionary {
        ["available": true, "appearance": [
            "mode": dark ? "dark" : "light", "systemMode": dark ? "dark" : "light",
            "webMode": dark ? "dark" : "light", "webModeAvailable": true, "webModeManaged": false,
            "commandPanelLayoutAvailable": true, "commandPanelLayoutManaged": false,
            "commandPanelLayout": configuration.dictionary, "spacePalette": ["available": false]
        ]] as NSDictionary
    }
    func settingChanged(key: String, value: Any) {
        guard key == "command_panel_layout", let dictionary = value as? [String: Any] else { return }
        configuration = Configuration(dictionary)
        preferences.set(configuration.dictionary, forKey: "configuration")
        panel.preview.configuration = configuration
        // Echo the latest state after the binding transaction, without recreating the editor.
        guard !snapshotPending else { return }; snapshotPending = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }; self.snapshotPending = false
            self.controls.updateSnapshot(self.snapshot())
        }
    }
    func actionInvoked(name: String, payload: NSDictionary) {
        if name == "close_command_bar_editor" { window.performClose(nil) }
    }
    @objc private func toggleAppearance() { dark.toggle(); preferences.set(dark, forKey: "dark"); applyAppearance(); controls.updateSnapshot(snapshot()) }
    private func applyAppearance() {
        window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        root.bar.wantsLayer = true
        root.bar.layer?.backgroundColor = NSColor(white: dark ? 0.13 : 0.94, alpha: 1).cgColor
        for case let button as NSButton in root.buttons {
            let ink: NSColor = dark ? .white : .black
            button.bezelColor = NSColor(white: dark ? 0.25 : 0.88, alpha: 1)
            button.contentTintColor = ink
            button.attributedTitle = NSAttributedString(string: button.title, attributes: [
                .foregroundColor: ink, .font: NSFont.systemFont(ofSize: 13)
            ])
        }
        root.stage.dark = dark; panel.dark = dark
    }
    @objc private func resetExamples() { panel.preview.reset(); panel.preview.focusSearch() }
    @objc private func resetSettings() {
        configuration = Configuration(); preferences.set(configuration.dictionary, forKey: "configuration")
        controls.updateSnapshot(snapshot()); panel.preview.configuration = configuration
    }
    @objc private func copyConfiguration() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(String(decoding: configuration.json, as: UTF8.self), forType: .string)
    }
    private func installMenu() {
        let menu = NSMenu(), app = NSMenu(), top = NSMenuItem()
        menu.addItem(top); top.submenu = app
        app.addItem(withTitle: "Quit Command Bar Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let edit = NSMenu(), editTop = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        menu.addItem(editTop); editTop.submenu = edit
        for (title, action, key) in [("Cut", #selector(NSText.cut(_:)), "x"), ("Copy", #selector(NSText.copy(_:)), "c"), ("Paste", #selector(NSText.paste(_:)), "v"), ("Select All", #selector(NSText.selectAll(_:)), "a")] { edit.addItem(withTitle: title, action: action, keyEquivalent: key) }
        NSApp.mainMenu = menu
    }
    func windowDidResize(_ notification: Notification) { panel.place() }
    func windowDidMove(_ notification: Notification) { panel.place() }
    func windowWillClose(_ notification: Notification) { panel.close(); NSApp.terminate(nil) }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
@MainActor
enum Main {
    static func main() {
        if CommandLine.arguments.count == 4, CommandLine.arguments[1] == "--quit-owned" {
            guard let pid = Int32(CommandLine.arguments[2]) else { exit(2) }
            guard let running = NSRunningApplication(processIdentifier: pid) else { return }
            let expected = URL(fileURLWithPath: CommandLine.arguments[3]).standardizedFileURL.resolvingSymlinksInPath()
            guard running.bundleIdentifier == "org.arcium.CommandBarStudio",
                  running.executableURL?.standardizedFileURL.resolvingSymlinksInPath() == expected else {
                fputs("Refusing to quit an unrecognized process.\n", stderr); exit(2)
            }
            guard running.terminate() else { fputs("Studio declined a normal quit.\n", stderr); exit(2) }
            let deadline = Date().addingTimeInterval(5)
            while !running.isTerminated && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
            if !running.isTerminated { fputs("Studio did not quit; no process was killed.\n", stderr); exit(2) }
            return
        }
        let app = NSApplication.shared
        let delegate = StudioApp()
        app.setActivationPolicy(.regular); app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
