import Foundation
@_silgen_name("uncompress")
func uncompress(_ destination: UnsafeMutablePointer<UInt8>, _ size: UnsafeMutablePointer<UInt>,
                _ source: UnsafePointer<UInt8>, _ count: UInt) -> Int32

struct Raster {
    let width: Int
    let height: Int
    var pixels: [UInt8]
    let profile: [String: Data]
    init(_ path: String) throws {
        // Compare exact unassociated PNG samples. CoreGraphics color conversion
        // and 8-bit premultiplication would lose low-alpha and transparent RGB.
        let data = [UInt8](try Data(contentsOf: URL(fileURLWithPath: path)))
        guard Array(data.prefix(8)) == [137,80,78,71,13,10,26,10] else { throw Failure.image(path) }
        func integer(_ offset: Int) -> Int {
            data[offset..<offset+4].reduce(0) { ($0 << 8) | Int($1) }
        }
        var cursor = 8, w = 0, h = 0, channels = 0
        var compressed = [UInt8](), colorProfile = [String: Data]()
        while cursor + 12 <= data.count {
            let size = integer(cursor)
            guard size <= data.count - cursor - 12 else { throw Failure.image(path) }
            let kind = String(bytes: data[cursor+4..<cursor+8], encoding: .ascii)!
            let body = cursor+8
            if kind == "IHDR" {
                guard size == 13, data[body+8] == 8, [2,6].contains(data[body+9]),
                      data[body+10] == 0, data[body+11] == 0, data[body+12] == 0 else { throw Failure.image(path) }
                w = integer(body); h = integer(body+4); channels = data[body+9] == 6 ? 4 : 3
            } else if kind == "IDAT" { compressed.append(contentsOf: data[body..<body+size]) }
            else if ["iCCP", "sRGB", "gAMA", "cHRM", "cICP"].contains(kind) {
                colorProfile[kind] = Data(data[body..<body+size])
            }
            cursor += size + 12
        }
        guard w > 0, h > 0, w <= 16384, h <= 16384, channels > 0, !compressed.isEmpty else { throw Failure.image(path) }
        width = w; height = h; profile = colorProfile
        let stride = w * channels
        var raw = [UInt8](repeating: 0, count: h * (stride+1)), count = UInt(h * (stride+1))
        let status = raw.withUnsafeMutableBufferPointer { destination in
            compressed.withUnsafeBufferPointer { source in
                uncompress(destination.baseAddress!, &count, source.baseAddress!, UInt(source.count))
            }
        }
        guard status == 0, count == UInt(raw.count) else { throw Failure.image(path) }
        pixels = [UInt8](); pixels.reserveCapacity(w*h*4)
        var previous = [UInt8](repeating: 0, count: stride)
        for y in 0..<h {
            let offset = y*(stride+1), mode = raw[offset]
            guard mode <= 4 else { throw Failure.image(path) }
            var row = Array(raw[offset+1..<offset+1+stride])
            for x in 0..<stride {
                let left = x >= channels ? Int(row[x-channels]) : 0
                let above = Int(previous[x]), upperLeft = x >= channels ? Int(previous[x-channels]) : 0
                var prediction = 0
                switch mode {
                case 1: prediction = left
                case 2: prediction = above
                case 3: prediction = (left+above)/2
                case 4:
                    let p = left+above-upperLeft
                    let a = abs(p-left), b = abs(p-above), c = abs(p-upperLeft)
                    prediction = a <= b && a <= c ? left : (b <= c ? above : upperLeft)
                default: break
                }
                row[x] = UInt8((Int(row[x])+prediction)&255)
            }
            for x in Swift.stride(from: 0, to: stride, by: channels) {
                pixels.append(contentsOf: row[x..<x+3]); pixels.append(channels == 4 ? row[x+3] : 255)
            }
            previous = row
        }
    }
}
enum Failure: Error { case image(String), input }
func difference(_ left: Raster, _ right: Raster, _ backdrop: [Int]) throws -> [String: Any] {
    guard left.profile == right.profile else { throw Failure.input }
    guard left.width == right.width && left.height == right.height else {
        return ["same_size": false, "sizes": [[left.width,left.height],[right.width,right.height]]]
    }
    var histogram = [Int](repeating: 0, count: 256)
    var alphaHistogram = [Int](repeating: 0, count: 256)
    var rgbError = 0
    for offset in stride(from: 0, to: left.pixels.count, by: 4) {
        let aAlpha = Int(left.pixels[offset+3]), bAlpha = Int(right.pixels[offset+3])
        alphaHistogram[abs(aAlpha-bAlpha)] += 1
        for channel in 0..<3 {
            let a = Int(left.pixels[offset+channel]), b = Int(right.pixels[offset+channel])
            rgbError += abs(a-b)
            let aComposite = (a*aAlpha + backdrop[channel] * (255-aAlpha) + 127) / 255
            let bComposite = (b*bAlpha + backdrop[channel] * (255-bAlpha) + 127) / 255
            histogram[abs(aComposite-bComposite)] += 1
        }
    }
    let count = histogram.reduce(0,+), pixels = alphaHistogram.reduce(0,+)
    var running = 0, p99 = 0
    for (delta, frequency) in histogram.enumerated() { running += frequency; if Double(running) >= Double(count)*0.99 { p99 = delta; break } }
    func mean(_ histogram: [Int], _ divisor: Int) -> Double {
        let sum = histogram.enumerated().reduce(0) { $0 + $1.offset * $1.element }
        return (Double(sum) / Double(divisor) * 100_000).rounded() / 100_000
    }
    return ["same_size": true, "mean_channel_error": mean(histogram,count),
        "mean_raw_rgb_error": (Double(rgbError)/Double(count)*100_000).rounded()/100_000,
        "mean_alpha_error": mean(alphaHistogram,pixels),
        "fraction_alpha_over_3": (Double(alphaHistogram[4...].reduce(0,+))/Double(pixels)*1_000_000).rounded()/1_000_000,
        "fraction_channels_over_3": (Double(histogram[4...].reduce(0,+))/Double(count)*1_000_000).rounded()/1_000_000, "p99_channel_error": p99]
}
do {
let jobs = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [[String: Any]]
var results: [String: Any] = [:]
for job in jobs {
    let left = try Raster(job["left"] as! String), right = try Raster(job["right"] as! String)
    let leftRepeat = try Raster(job["left_repeat"] as! String), rightRepeat = try Raster(job["right_repeat"] as! String)
    let backdrop = job["backdrop"] as! [Int]
    results[job["name"] as! String] = ["cross_host": try difference(left,right,backdrop),
        "browser_repeat_noise": try difference(left,leftRepeat,backdrop), "studio_repeat_noise": try difference(right,rightRepeat,backdrop)]
}
try JSONSerialization.data(withJSONObject: results, options: [.sortedKeys]).write(to: URL(fileURLWithPath: CommandLine.arguments[2]), options: .atomic)
} catch {
    FileHandle.standardError.write(Data("PNG comparison rejected: \(error)\n".utf8))
    exit(1)
}
