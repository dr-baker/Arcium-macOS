import AppKit
import Foundation
import Darwin

let manager = FileManager.default

enum InstallError: LocalizedError {
    case exists, missing, unsafeProfile
    var errorDescription: String? {
        switch self {
        case .exists: return "Arcium is already in Applications. Quit it and move the old app to the Trash before installing this preview. Your browsing data stays in place."
        case .missing: return "The installer is incomplete. Download it again."
        case .unsafeProfile: return "The Arcium data folder is a symbolic link. Install the app manually to keep that setup."
        }
    }
}

@discardableResult
func seedPreferences(_ template: URL, profile: URL) throws -> Bool {
    // A default template must never overwrite an existing browser profile.
    if manager.fileExists(atPath: profile.path) {
        let values = try profile.resourceValues(forKeys: [.isSymbolicLinkKey])
        if values.isSymbolicLink == true { throw InstallError.unsafeProfile }
        return false
    }
    let object = try JSONSerialization.jsonObject(with: Data(contentsOf: template))
    guard object is [String: Any] else { throw InstallError.missing }
    if mkdir(profile.path, 0o700) != 0 {
        if errno == EEXIST { return false }
        throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
    }
    let target = profile.appendingPathComponent("Chromium Initial Preferences")
    try Data(contentsOf: template).write(to: target, options: .withoutOverwriting)
    try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: target.path)
    return true
}

func selfTest() throws {
    let temporary = manager.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try manager.createDirectory(at: temporary, withIntermediateDirectories: true)
    defer { try? manager.removeItem(at: temporary) }
    let template = temporary.appendingPathComponent("template.json")
    try Data("{\"helium\":{\"browser\":{\"layout\":2}}}".utf8).write(to: template)
    let fresh = temporary.appendingPathComponent("fresh")
    guard try seedPreferences(template, profile: fresh) else { fatalError("fresh profile skipped") }
    let target = fresh.appendingPathComponent("Chromium Initial Preferences")
    let before = try Data(contentsOf: target)
    try Data("{}".utf8).write(to: template)
    guard try !seedPreferences(template, profile: fresh),
          try Data(contentsOf: target) == before else { fatalError("existing profile changed") }
    let existing = temporary.appendingPathComponent("existing")
    try manager.createDirectory(at: existing, withIntermediateDirectories: true)
    guard try !seedPreferences(template, profile: existing),
          !manager.fileExists(atPath: existing.appendingPathComponent("Chromium Initial Preferences").path)
    else { fatalError("existing empty profile changed") }
    let link = temporary.appendingPathComponent("link")
    try manager.createSymbolicLink(at: link, withDestinationURL: existing)
    do { _ = try seedPreferences(template, profile: link); fatalError("symlink accepted") }
    catch InstallError.unsafeProfile { }
    print("PASS: fresh defaults, existing profile preservation, symbolic-link refusal")
}

if CommandLine.arguments.contains("--self-test") {
    do { try selfTest(); exit(0) }
    catch { fputs("\(error)\n", stderr); exit(1) }
}

let application = NSApplication.shared
application.setActivationPolicy(.regular)
application.activate(ignoringOtherApps: true)
let prompt = NSAlert()
prompt.messageText = "Install Arcium"
prompt.informativeText = "Install the browser in Applications. New profiles start with a pastel sidebar, Favorites and Pins, Peek, and recent-tab switching. Existing browsing data stays unchanged."
prompt.addButton(withTitle: "Install")
prompt.addButton(withTitle: "Cancel")
guard prompt.runModal() == .alertFirstButtonReturn else { exit(0) }

do {
    guard let resources = Bundle.main.resourceURL else { throw InstallError.missing }
    let source = resources.appendingPathComponent("Arcium.app")
    let template = resources.appendingPathComponent("initial-preferences.json")
    guard manager.fileExists(atPath: source.appendingPathComponent("Contents/MacOS/Helium").path)
    else { throw InstallError.missing }
    let applications = URL(fileURLWithPath: "/Applications", isDirectory: true)
    let destination = applications.appendingPathComponent("Arcium.app")
    guard !manager.fileExists(atPath: destination.path) else { throw InstallError.exists }
    let staging = applications.appendingPathComponent(".Arcium-install-\(UUID().uuidString).app")
    defer { try? manager.removeItem(at: staging) }
    try manager.copyItem(at: source, to: staging)
    let support = try manager.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                  appropriateFor: nil, create: true)
    _ = try seedPreferences(template, profile: support.appendingPathComponent("Arcium"))
    try manager.moveItem(at: staging, to: destination)
    let complete = NSAlert()
    complete.messageText = "Arcium is installed"
    complete.informativeText = "Open Arcium from Applications. Check the release page for updates. Browser updates are installed manually."
    complete.addButton(withTitle: "Open Arcium")
    complete.addButton(withTitle: "Done")
    if complete.runModal() == .alertFirstButtonReturn {
        NSWorkspace.shared.openApplication(at: destination,
            configuration: NSWorkspace.OpenConfiguration()) { _, error in
            if let error { NSAlert(error: error).runModal() }
            NSApplication.shared.terminate(nil)
        }
        application.run()
    }
} catch {
    NSAlert(error: error).runModal()
    exit(1)
}
