import AppKit
import ImageIO
import UniformTypeIdentifiers

@MainActor
enum BackgroundAssets {
    private static let images: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        cache.countLimit = 4
        return cache
    }()
    private static var directory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Arcium Glass Lab/Backgrounds", isDirectory: true)
    }
    private static func url(_ id: String) -> URL? {
        guard UUID(uuidString: id) != nil else { return nil }
        return directory.appendingPathComponent(id).appendingPathExtension("jpg")
    }
    static func image(_ id: String?) -> NSImage? {
        guard let id, let file = url(id) else { return nil }
        if let cached = images.object(forKey: id as NSString) { return cached }
        guard let image = NSImage(contentsOf: file) else { return nil }
        images.setObject(image, forKey: id as NSString)
        return image
    }
    static func data(_ id: String?) -> Data? {
        guard let id, let file = url(id) else { return nil }
        return try? Data(contentsOf: file)
    }
    static func store(file: URL) throws -> String {
        guard let source = CGImageSourceCreateWithURL(file as CFURL, nil) else { throw invalidImage }
        return try store(source: source)
    }
    static func store(data: Data) throws -> String {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { throw invalidImage }
        return try store(source: source)
    }
    private static var invalidImage: NSError {
        NSError(domain: "GlassLab", code: 2, userInfo: [NSLocalizedDescriptionKey: "Choose a readable image file."])
    }
    private static func store(source: CGImageSource) throws -> String {
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: 1800,
            kCGImageSourceCreateThumbnailWithTransform: true
        ]
        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { throw invalidImage }
        let encoded = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(encoded, UTType.jpeg.identifier as CFString, 1, nil) else { throw invalidImage }
        CGImageDestinationAddImage(destination, thumbnail, [kCGImageDestinationLossyCompressionQuality: 0.85] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw invalidImage }
        let id = UUID().uuidString
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try (encoded as Data).write(to: url(id)!, options: .atomic)
        images.setObject(NSImage(cgImage: thumbnail, size: .zero), forKey: id as NSString)
        return id
    }
}
