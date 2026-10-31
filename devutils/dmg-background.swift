// Render the static Finder background, without baking in draggable file icons.
// Run: swift devutils/dmg-background.swift resources/dmg-background
import AppKit

let destination = CommandLine.arguments[1]
let width = 640.0
let height = 420.0
let stops: [(Double, [Double])] = [
    (0, [237, 155, 198]), (0.44, [246, 210, 228]),
    (0.81, [253, 243, 249]), (1, [255, 249, 252])
]

func render(scale: Int, suffix: String) throws {
    let pixelsWide = Int(width) * scale
    let pixelsHigh = Int(height) * scale
    let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: pixelsWide, pixelsHigh: pixelsHigh,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: pixelsWide * 4, bitsPerPixel: 32)!
    let pixels = bitmap.bitmapData!
    for y in 0..<pixelsHigh {
        for x in 0..<pixelsWide {
            let dx = (Double(x) / Double(scale) - width * 0.45) / (width * 0.9)
            let dy = (Double(y) / Double(scale) - height * 1.12) / (height * 0.67)
            let radius = min(1, sqrt(dx * dx + dy * dy))
            let upper = stops.firstIndex { $0.0 >= radius } ?? stops.count - 1
            let lower = max(0, upper - 1)
            let span = stops[upper].0 - stops[lower].0
            let fraction = span == 0 ? 0 : (radius - stops[lower].0) / span
            let offset = (y * pixelsWide + x) * 4
            for channel in 0..<3 {
                pixels[offset + channel] = UInt8(
                    (stops[lower].1[channel] * (1 - fraction)
                     + stops[upper].1[channel] * fraction).rounded())
            }
            pixels[offset + 3] = 255
        }
    }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSGraphicsContext.current!.cgContext.scaleBy(x: CGFloat(scale), y: CGFloat(scale))

    func color(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> NSColor {
        NSColor(srgbRed: r / 255, green: g / 255, blue: b / 255, alpha: 1)
    }
    func text(_ string: String, top: CGFloat, size: CGFloat,
              weight: NSFont.Weight, ink: NSColor) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: size, weight: weight),
            .foregroundColor: ink
        ]
        let label = NSAttributedString(string: string, attributes: attributes)
        let bounds = label.size()
        label.draw(at: NSPoint(x: (width - bounds.width) / 2,
                               y: height - top - bounds.height))
    }
    let ink = color(80, 34, 61)
    text("Welcome to Arcium.", top: 52, size: 28, weight: .medium, ink: ink)
    text("Drag Arcium to Applications to install.", top: 340, size: 16,
         weight: .medium, ink: ink)
    text("Then open Arcium from Applications.", top: 373, size: 12,
         weight: .regular, ink: color(137, 100, 121))
    color(162, 88, 128).setStroke()
    let arrow = NSBezierPath()
    arrow.lineWidth = 2.6
    arrow.lineCapStyle = .round
    arrow.lineJoinStyle = .round
    arrow.move(to: NSPoint(x: 282, y: height - 226))
    arrow.line(to: NSPoint(x: 358, y: height - 226))
    arrow.move(to: NSPoint(x: 343, y: height - 212))
    arrow.line(to: NSPoint(x: 358, y: height - 226))
    arrow.line(to: NSPoint(x: 343, y: height - 240))
    arrow.stroke()
    NSGraphicsContext.restoreGraphicsState()
    bitmap.size = NSSize(width: width, height: height)
    try bitmap.representation(using: .png, properties: [:])!
        .write(to: URL(fileURLWithPath: destination + suffix + ".png"))
}

try render(scale: 1, suffix: "")
try render(scale: 2, suffix: "@2x")
