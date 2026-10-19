import AppKit
import SwiftUI

@main
struct GlassLabApplication {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = LabDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}

@MainActor
final class LabDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let store = LabStore()
    var controller: PanelController!
    var window: NSWindow!
    var eventMonitor: Any?
    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = PanelController(store: store)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 920), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Arcium Glass Lab"
        window.minSize = NSSize(width: 1140, height: 800)
        window.isReleasedWhenClosed = false
        window.delegate = self
        let content = NSHostingView(rootView: LabView(store: store, controller: controller))
        content.sizingOptions = []
        window.contentView = content
        window.setFrameAutosaveName("GlassLabWindow")
        window.center()
        store.onChange = { [weak self] in
            DispatchQueue.main.async {
                guard let self else { return }
                self.window.appearance = NSAppearance(named: self.store.document.dark ? .darkAqua : .aqua)
                self.controller.refresh()
            }
        }
        let menu = NSMenu()
        let application = NSMenuItem(); let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Arcium Glass Lab", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Arcium Glass Lab", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        application.submenu = appMenu; menu.addItem(application)
        let edit = NSMenuItem(title: "Edit", action: nil, keyEquivalent: ""); let editMenu = NSMenu(title: "Edit")
        for (title, action, key) in [("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        edit.submenu = editMenu; menu.addItem(edit)
        NSApplication.shared.mainMenu = menu
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            if NSApplication.shared.modalWindow != nil { return event }
            if event.modifierFlags.contains(.command), event.charactersIgnoringModifiers == "l" {
                self.store.document.preview = .command; self.store.panelVisible = true; return nil
            }
            if event.modifierFlags.contains(.control), event.keyCode == 48 {
                self.store.document.preview = .mru; self.store.panelVisible = true
                self.store.selectedItem = (self.store.selectedItem+1)%3; return nil
            }
            if event.keyCode == 53 { self.store.panelVisible = false; return nil }
            return event
        }
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        DispatchQueue.main.async { [weak self] in self?.controller.refresh() }
    }
    func windowWillClose(_ notification: Notification) { NSApplication.shared.terminate(nil) }
    func windowDidResize(_ notification: Notification) { controller?.refresh() }
    func windowDidMove(_ notification: Notification) { controller?.refresh() }
    func windowDidBecomeKey(_ notification: Notification) { controller?.refresh() }
    func windowDidResignKey(_ notification: Notification) { controller?.refresh() }
    func applicationDidBecomeActive(_ notification: Notification) { controller?.refresh() }
    func applicationDidResignActive(_ notification: Notification) { controller?.refresh() }
    func applicationWillTerminate(_ notification: Notification) {
        store.save()
        controller?.close()
        if let eventMonitor { NSEvent.removeMonitor(eventMonitor) }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
