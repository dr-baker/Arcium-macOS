import AppKit
import QuartzCore

@MainActor
private final class ScopeButton: NSButton {
    override func draw(_ dirtyRect: NSRect) {} // Foreground is painted with the shared rail geometry.
}

@MainActor
final class CommandPreview: NSView, NSTextFieldDelegate {
    var configuration = Configuration() { didSet { updateResults(); needsLayout = true; redraw() } }
    var dark = true { didSet { updateColors(); redraw() } }
    var onHeightChange: (() -> Void)?
    var onContourChange: ((CGPath) -> Void)?
    let input = NSTextField()
    private(set) var selectedScope = 0
    private(set) var rows = Fixture.rows(query: "", scope: 0, limit: 8)
    private(set) var selectedRow = 0
    private var rowOffset = 0
    private var scopeFocus = false
    private var hovered = false
    private var reveal: CGFloat = 0, focus: CGFloat = 0
    private var weights: [CGFloat] = [1, 0, 0, 0, 0, 0]
    private var timer: Timer?
    private var tracking: NSTrackingArea?
    private var feedback = ""
    private var scopeButtons: [NSButton] = []
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    var desiredHeight: CGFloat {
        ProductionContract.railReserve + ProductionContract.searchHeight
            + CGFloat(min(10, max(1, rows.count))) * ProductionContract.rowHeight + ProductionContract.footerHeight
    }
    private var bodyTop: CGFloat { ProductionContract.railReserve }
    private var textColor: NSColor { dark ? NSColor(white: 0.94, alpha: 1) : NSColor(white: 0.12, alpha: 1) }
    private var secondary: NSColor { textColor.withAlphaComponent(0.58) }
    private let gold = NSColor(srgbRed: 0.79, green: 0.71, blue: 0.48, alpha: 1)
    private let colors: [NSColor] = [.systemPurple, .systemBlue, .systemYellow, .systemRed, .labelColor, .systemGreen]

    override init(frame: NSRect) {
        super.init(frame: frame)
        input.isBordered = false; input.drawsBackground = false; input.focusRingType = .none
        input.font = .systemFont(ofSize: 20)
        input.placeholderString = "Search tabs, Pins, Favorites and the web"
        input.delegate = self
        input.setAccessibilityIdentifier("studio.query")
        input.setAccessibilityLabel("Command bar search")
        addSubview(input)
        for (index, name) in Fixture.scopes.enumerated() {
            let button = ScopeButton(title: "", target: self, action: #selector(selectScope(_:)))
            button.isBordered = false; button.tag = index
            button.setAccessibilityLabel(name + " scope")
            button.setAccessibilityIdentifier("studio.scope.\(index)")
            addSubview(button); scopeButtons.append(button)
        }
        setAccessibilityIdentifier("studio.preview")
        updateColors()
    }
    required init?(coder: NSCoder) { fatalError("No storyboard") }

    func focusSearch() { window?.makeFirstResponder(input); scopeFocus = false; animate() }
    func reset() {
        input.stringValue = ""; selectedScope = 0; selectedRow = 0; rowOffset = 0
        scopeFocus = false; hovered = false; feedback = ""; updateResults(); animate()
    }
    private func updateColors() { input.textColor = textColor; input.appearance = NSAppearance(named: dark ? .darkAqua : .aqua) }
    @objc private func selectScope(_ sender: NSButton) {
        selectedScope = sender.tag; scopeFocus = true; window?.makeFirstResponder(input)
        updateResults(); animate()
    }
    private func updateResults() {
        rows = Fixture.rows(query: input.stringValue, scope: selectedScope, limit: configuration.resultCount)
        selectedRow = min(selectedRow, max(0, rows.count - 1)); rowOffset = min(rowOffset, max(0, rows.count - 10))
        onHeightChange?()
    }
    func controlTextDidChange(_ obj: Notification) {
        scopeFocus = false; selectedRow = 0; rowOffset = 0; feedback = ""; updateResults(); animate()
    }
    func controlTextDidBeginEditing(_ obj: Notification) { animate() }
    func controlTextDidEndEditing(_ obj: Notification) { scopeFocus = false; animate() }
    func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
        switch selector {
        case #selector(NSResponder.moveUp(_:)):
            if selectedRow == 0 { scopeFocus = true } else { selectedRow -= 1 }
        case #selector(NSResponder.moveDown(_:)):
            if scopeFocus { scopeFocus = false } else { selectedRow = min(rows.count - 1, selectedRow + 1) }
        case #selector(NSResponder.moveLeft(_:)) where scopeFocus:
            selectedScope = (selectedScope + Fixture.scopes.count - 1) % Fixture.scopes.count; updateResults()
        case #selector(NSResponder.moveRight(_:)) where scopeFocus:
            selectedScope = (selectedScope + 1) % Fixture.scopes.count; updateResults()
        case #selector(NSResponder.insertNewline(_:)):
            feedback = "Example selected · no page opened"
        case #selector(NSResponder.cancelOperation(_:)):
            reset()
        default: return false
        }
        if selectedRow < rowOffset { rowOffset = selectedRow }
        if selectedRow >= rowOffset + 10 { rowOffset = selectedRow - 9 }
        animate(); return true
    }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let tracking { removeTrackingArea(tracking) }
        let area = NSTrackingArea(rect: bounds, options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect], owner: self)
        addTrackingArea(area); tracking = area
    }
    override func mouseMoved(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        let value = point.y < bodyTop + 8
        if hovered != value { hovered = value; animate() }
    }
    override func mouseExited(with event: NSEvent) { hovered = false; animate() }
    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        if point.y < bodyTop + 8, let index = scopeFrames.firstIndex(where: { $0.contains(point) }) {
            selectedScope = index; scopeFocus = true; window?.makeFirstResponder(input)
            updateResults(); animate(); return
        }
        let index = Int((point.y - bodyTop - ProductionContract.searchHeight) / ProductionContract.rowHeight) + rowOffset
        if point.y >= bodyTop + ProductionContract.searchHeight && rows.indices.contains(index) {
            selectedRow = index; scopeFocus = false; feedback = "Example selected · no page opened"; animate()
        } else { focusSearch() }
    }
    override func rightMouseDown(with event: NSEvent) {
        let menu = NSMenu()
        for title in ["Open in new tab", "Move to another Space", "Copy link"] {
            let item = NSMenuItem(title: title, action: #selector(exampleAction(_:)), keyEquivalent: "")
            item.target = self; menu.addItem(item)
        }
        NSMenu.popUpContextMenu(menu, with: event, for: self)
    }
    @objc private func exampleAction(_ sender: NSMenuItem) { feedback = "\(sender.title) · example only"; redraw() }
    override func scrollWheel(with event: NSEvent) {
        rowOffset = min(max(0, rows.count - 10), max(0, rowOffset + (event.scrollingDeltaY < 0 ? 1 : -1)))
        redraw()
    }
    private var scopeFrames: [CGRect] {
        let labels = Fixture.scopes.map { ($0 as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 11, weight: .medium)]).width + 7 }
        return ScopeLayout.frames(width: bounds.width, bodyTop: bodyTop, config: configuration, reveal: reveal, weights: weights, labelWidths: labels)
    }
    override func layout() {
        super.layout()
        input.frame = CGRect(x: 50, y: bodyTop + 19, width: max(20, bounds.width - 72), height: 28)
        redraw()
    }
    private func animate() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 1 / 60, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.tick() }
        }
    }
    private func tick() {
        var moving = false
        func approach(_ value: inout CGFloat, _ target: CGFloat, _ factor: CGFloat) {
            value += (target - value) * factor
            if abs(value - target) < 0.002 { value = target } else { moving = true }
        }
        approach(&reveal, scopeFocus || hovered ? 1 : 0, 0.38)
        let editing = window?.firstResponder is NSTextView
        approach(&focus, scopeFocus && editing ? 1 : 0, 0.55)
        for index in weights.indices { approach(&weights[index], index == selectedScope ? 1 : 0, 0.55) }
        redraw()
        if !moving { timer?.invalidate(); timer = nil }
    }
    private func redraw() {
        needsDisplay = true
        for (button, frame) in zip(scopeButtons, scopeFrames) { button.frame = frame }
        onContourChange?(contour())
    }

    func contour() -> CGPath {
        let body = CGRect(x: 0, y: bodyTop, width: bounds.width, height: max(0, bounds.height - bodyTop))
        let path = CGMutablePath()
        let frames = scopeFrames
        if !configuration.connected {
            path.addRoundedRect(in: body, cornerWidth: 13, cornerHeight: 13)
            for frame in frames {
                let visible = CGRect(x: frame.minX, y: frame.minY, width: frame.width, height: min(frame.height, max(0, bodyTop - frame.minY)))
                if visible.height > 0 { path.addPath(topRounded(visible)) }
            }
            return path
        }
        if configuration.scopeWidth == 0, let first = frames.first {
            // Quartz approximation of Skia's tangent crest/valley contour.
            let crest = first.minY, valley = bodyTop - ProductionContract.geometry[configuration.scopeReveal].detent
            path.move(to: CGPoint(x: 13, y: crest))
            for pair in zip(frames, frames.dropFirst()) {
                let middle = (pair.0.maxX + pair.1.minX) / 2
                let r = min(10, (valley - crest) / 2)
                path.addLine(to: CGPoint(x: middle - 2 * r, y: crest))
                path.addCurve(to: CGPoint(x: middle, y: valley), control1: CGPoint(x: middle - r, y: crest), control2: CGPoint(x: middle - r, y: valley))
                path.addCurve(to: CGPoint(x: middle + 2 * r, y: crest), control1: CGPoint(x: middle + r, y: valley), control2: CGPoint(x: middle + r, y: crest))
            }
            finishBody(path, top: crest)
        } else {
            path.move(to: CGPoint(x: 13, y: bodyTop))
            for frame in frames where frame.minY < bodyTop - 1 {
                let shoulder = min(4, (bodyTop - frame.minY) * 0.3)
                let cap = max(0, min(13, (frame.width - 4) / 2, bodyTop - frame.minY - shoulder))
                path.addLine(to: CGPoint(x: frame.minX - shoulder, y: bodyTop))
                path.addQuadCurve(to: CGPoint(x: frame.minX, y: bodyTop - shoulder), control: CGPoint(x: frame.minX, y: bodyTop))
                path.addLine(to: CGPoint(x: frame.minX, y: frame.minY + cap))
                path.addQuadCurve(to: CGPoint(x: frame.minX + cap, y: frame.minY), control: frame.origin)
                path.addLine(to: CGPoint(x: frame.maxX - cap, y: frame.minY))
                path.addQuadCurve(to: CGPoint(x: frame.maxX, y: frame.minY + cap), control: CGPoint(x: frame.maxX, y: frame.minY))
                path.addLine(to: CGPoint(x: frame.maxX, y: bodyTop - shoulder))
                path.addQuadCurve(to: CGPoint(x: frame.maxX + shoulder, y: bodyTop), control: CGPoint(x: frame.maxX, y: bodyTop))
            }
            finishBody(path, top: bodyTop)
        }
        return path
    }
    private func finishBody(_ path: CGMutablePath, top: CGFloat) {
        let w = bounds.width, h = bounds.height
        path.addLine(to: CGPoint(x: w - 13, y: top))
        path.addQuadCurve(to: CGPoint(x: w, y: top + 13), control: CGPoint(x: w, y: top))
        path.addLine(to: CGPoint(x: w, y: h - 13))
        path.addQuadCurve(to: CGPoint(x: w - 13, y: h), control: CGPoint(x: w, y: h))
        path.addLine(to: CGPoint(x: 13, y: h))
        path.addQuadCurve(to: CGPoint(x: 0, y: h - 13), control: CGPoint(x: 0, y: h))
        path.addLine(to: CGPoint(x: 0, y: top + 13))
        path.addQuadCurve(to: CGPoint(x: 13, y: top), control: CGPoint(x: 0, y: top)); path.closeSubpath()
    }
    private func topRounded(_ rect: CGRect) -> CGPath {
        let p = CGMutablePath(), r = min(13, rect.height, rect.width / 2)
        p.move(to: CGPoint(x: rect.minX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.minX, y: rect.minY + r))
        p.addQuadCurve(to: CGPoint(x: rect.minX + r, y: rect.minY), control: rect.origin)
        p.addLine(to: CGPoint(x: rect.maxX - r, y: rect.minY))
        p.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.minY + r), control: CGPoint(x: rect.maxX, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY)); p.closeSubpath(); return p
    }
    private func text(_ string: String, _ rect: CGRect, size: CGFloat = 14, color: NSColor? = nil, bold: Bool = false) {
        let paragraph = NSMutableParagraphStyle(); paragraph.lineBreakMode = .byTruncatingTail
        (string as NSString).draw(in: rect, withAttributes: [.font: NSFont.systemFont(ofSize: size, weight: bold ? .medium : .regular), .foregroundColor: color ?? textColor, .paragraphStyle: paragraph])
    }
    private func symbol(_ name: String, _ rect: CGRect, color: NSColor) {
        guard let image = NSImage(systemSymbolName: name, accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: rect.height - 1, weight: .medium)) else { return }
        let tinted = NSImage(size: image.size, flipped: false) { bounds in
            color.set(); image.draw(in: bounds); bounds.fill(using: .sourceAtop); return true
        }
        tinted.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
    }
    override func draw(_ dirtyRect: NSRect) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        let path = contour(), frames = scopeFrames
        ctx.saveGState(); ctx.addPath(path); ctx.clip()
        (dark ? NSColor(white: 0.08, alpha: 0.32) : NSColor(white: 1, alpha: 0.28)).setFill(); bounds.fill()
        if configuration.scopeTints {
            for (i, frame) in frames.enumerated() {
                let height = min(frame.height, max(0, bodyTop - frame.minY))
                let opacity = Lighting.radiance(width: frame.width, height: height, strength: configuration.glowStrength, focus: focus, selected: weights[i])
                if !configuration.connected { ctx.saveGState(); ctx.addPath(topRounded(CGRect(x: frame.minX, y: frame.minY, width: frame.width, height: height))); ctx.clip() }
                if i == 0 {
                    glow(ctx, x: frame.midX - 0.24 * frame.width, y: frame.minY, width: frame.width, height: height, color: NSColor(srgbRed: 174/255, green: 112/255, blue: 245/255, alpha: 1), power: opacity * 0.4)
                    glow(ctx, x: frame.midX + 0.24 * frame.width, y: frame.minY, width: frame.width, height: height, color: NSColor(srgbRed: 100/255, green: 159/255, blue: 1, alpha: 1), power: opacity * 0.4)
                    glow(ctx, x: frame.midX, y: frame.minY, width: frame.width, height: height, color: NSColor(srgbRed: 89/255, green: 206/255, blue: 157/255, alpha: 1), power: opacity * 0.2)
                } else { glow(ctx, x: frame.midX, y: frame.minY, width: frame.width, height: height, color: colors[i], power: opacity) }
                if !configuration.connected { ctx.restoreGState() }
            }
        }
        ctx.restoreGState()
        for (i, frame) in frames.enumerated() {
            ctx.saveGState(); ctx.clip(to: frame)
            let hidden = ProductionContract.geometry[configuration.scopeReveal].hiddenIcons
            ctx.setAlpha(hidden ? reveal : 1)
            let label = weights[i] * reveal * min(max(0, frame.width - 26), CGFloat((Fixture.scopes[i] as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 11, weight: .medium)]).width + 7))
            let x = frame.midX - (16 + label) / 2
            symbol(Fixture.symbols[i], CGRect(x: x, y: frame.minY + CGFloat(ProductionContract.geometry[configuration.scopeReveal].padding) + 7, width: 16, height: 16), color: i == 0 ? .systemBlue : colors[i])
            if label > 1 { ctx.setAlpha(weights[i] * reveal); text(Fixture.scopes[i], CGRect(x: x + 23, y: frame.minY + 8, width: label - 7, height: 18), size: 11, bold: true) }
            ctx.restoreGState()
        }
        symbol("magnifyingglass", CGRect(x: 23, y: bodyTop + 24, width: 18, height: 18), color: gold)
        secondary.withAlphaComponent(0.18).setFill(); CGRect(x: 18, y: bodyTop + ProductionContract.searchHeight - 1, width: bounds.width - 36, height: 1).fill()
        let firstY = bodyTop + ProductionContract.searchHeight
        let rowHeight = ProductionContract.rowHeight
        for (visible, index) in (rowOffset..<min(rows.count, rowOffset + 10)).enumerated() {
            let row = rows[index], y = firstY + CGFloat(visible) * rowHeight
            let selected = index == selectedRow && !scopeFocus
            let ink = selected ? NSColor(white: 0.13, alpha: 1) : textColor
            if selected { gold.setFill(); NSBezierPath(roundedRect: CGRect(x: 14, y: y + 3, width: bounds.width - 28, height: rowHeight - 4), xRadius: 7, yRadius: 7).fill() }
            if configuration.activityDots && row.activity != .none {
                let dot = CGRect(x: 25, y: y + 20, width: 5, height: 5)
                ink.withAlphaComponent(0.7).set(); let circle = NSBezierPath(ovalIn: dot.insetBy(dx: row.activity == .dot ? 0 : -2, dy: row.activity == .dot ? 0 : -2))
                if row.activity == .dot { circle.fill() } else { circle.lineWidth = 1; circle.stroke(); if row.activity == .circleDot { NSBezierPath(ovalIn: dot.insetBy(dx: 1, dy: 1)).fill() } }
            }
            let symbols = ["Tab": "globe", "Pin": "pin", "Favorite": "star", "Folder": "folder", "History": "clock", "Search": "magnifyingglass", "Action": "ellipsis.circle"]
            symbol(symbols[row.category] ?? "globe", CGRect(x: 43, y: y + 13, width: 17, height: 17), color: ink)
            let categoryWidth = CGFloat((row.category as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 11)]).width + 12)
            let titleWidth = min(bounds.width * 0.42, CGFloat((row.title as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 15)]).width))
            text(row.title, CGRect(x: 75, y: y + 11, width: titleWidth, height: 23), size: 15, color: ink)
            let labelX = 83 + titleWidth
            if configuration.labels == 0 { ink.withAlphaComponent(0.1).setFill(); NSBezierPath(roundedRect: CGRect(x: labelX - 2, y: y + 12, width: categoryWidth, height: 20), xRadius: 6, yRadius: 6).fill() }
            text((configuration.labels == 2 ? "· " : "") + row.category, CGRect(x: labelX, y: y + 15, width: categoryWidth + 8, height: 17), size: 11, color: ink.withAlphaComponent(0.65))
            let cue: String
            switch configuration.icons {
            case 0: cue = row.destination == .action ? "•••" : row.destination == .switchTab ? "↪" : "↗"
            case 1: cue = row.destination == .switchTab ? "↪" : "→"
            case 3: cue = selected ? "↩" : ""
            default: cue = row.destination == .action ? "Action" : row.destination == .switchTab ? "Switch" : "Go"
            }
            text(cue, CGRect(x: bounds.width - 78, y: y + 15, width: 58, height: 19), size: 11, color: ink.withAlphaComponent(0.65))
        }
        text(feedback.isEmpty ? "↑ Scopes    ↓ Results    ↩ Preview    Right-click for actions" : feedback,
             CGRect(x: 23, y: bounds.height - 31, width: bounds.width - 46, height: 22), size: 11, color: secondary)
    }
    private func glow(_ ctx: CGContext, x: CGFloat, y: CGFloat, width: CGFloat, height: CGFloat, color: NSColor, power: CGFloat) {
        guard height > 0, power > 0 else { return }
        ctx.saveGState()
        ctx.clip(to: CGRect(x: 0, y: y, width: bounds.width, height: bounds.height - y))
        ctx.translateBy(x: x, y: y); ctx.scaleBy(x: width / 2 + 20, y: height + 20)
        let stops: [CGFloat] = [1, 0.52, 0.18, 0.05, 0]
        let colors = stops.map { color.withAlphaComponent(min(1, power * $0)).cgColor } as CFArray
        if let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 0.25, 0.5, 0.75, 1]) {
            ctx.drawRadialGradient(gradient, startCenter: .zero, startRadius: 0, endCenter: .zero, endRadius: 1, options: [])
        }
        ctx.restoreGState()
    }
}
