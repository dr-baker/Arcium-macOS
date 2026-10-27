import Foundation

struct ScopeGeometry {
    var restingRise, revealedRise, restingHeight: CGFloat
    var padding: Int
    var hiddenIcons: Bool
    var detent: CGFloat
}

struct ExampleRow: Equatable {
    enum Destination { case go, switchTab, action }
    enum Activity { case none, dot, circle, circleDot }
    var title, detail, category: String
    var destination: Destination
    var activity: Activity
}

struct Configuration: Equatable {
    var labels = 1, icons = 2, scopeReveal = 5, scopeWidth = 0, resultCount = 8
    var connected = true, scopeTints = true, activityDots = true
    var glowStrength = 0.75

    init() {}
    init(_ dictionary: [String: Any]) {
        func integer(_ key: String, _ fallback: Int, _ range: ClosedRange<Int>) -> Int {
            guard let n = dictionary[key] as? NSNumber,
                  CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite,
                  n.doubleValue.rounded() == n.doubleValue else { return fallback }
            return Int(min(Double(range.upperBound), max(Double(range.lowerBound), n.doubleValue)))
        }
        labels = integer("labels", 1, 0...2)
        icons = integer("icons", 2, 0...3)
        scopeReveal = integer("scope_reveal", 5, 0...5)
        scopeWidth = integer("scope_width", 0, 0...2)
        resultCount = integer("result_count", 8, 1...20)
        connected = dictionary["connected"] as? Bool ?? true
        scopeTints = dictionary["scope_tints"] as? Bool ?? true
        activityDots = dictionary["activity_dots"] as? Bool ?? true
        if let n = dictionary["glow_strength"] as? NSNumber,
           CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite {
            glowStrength = min(2, max(0, n.doubleValue))
        }
        if !connected && scopeWidth == 0 { scopeWidth = 2 }
    }
    var dictionary: [String: Any] {
        ["labels": labels, "icons": icons, "scope_reveal": scopeReveal,
         "scope_width": scopeWidth, "result_count": resultCount, "connected": connected,
         "scope_tints": scopeTints, "activity_dots": activityDots, "glow_strength": glowStrength]
    }
    var json: Data { (try? JSONSerialization.data(withJSONObject: dictionary, options: [.prettyPrinted, .sortedKeys])) ?? Data() }
}

enum Fixture {
    static let scopes = ["Omni", "Web", "Saved", "YouTube", "X", "ChatGPT"]
    static let symbols = ["sparkle", "globe", "pin", "play.rectangle.fill", "xmark", "bubble.left.and.text.bubble.right"]
    static func rows(query: String, scope: Int, limit: Int) -> [ExampleRow] {
        let count = min(20, max(1, limit))
        var examples = (0..<20).map { i -> ExampleRow in
            var row = ProductionContract.examples[i % ProductionContract.examples.count]
            if i >= 8 { row.title += " \(i + 1)" }
            if scope != 0 && scope != 2 { row.title = scopes[scope] + " · " + row.title }
            return row
        }
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty {
            examples = examples.filter { "\($0.title) \($0.detail) \($0.category)".localizedCaseInsensitiveContains(text) }
            examples = Array(examples.prefix(count - 1))
            examples.append(ExampleRow(title: "Search \(scopes[scope]) for “\(text)”", detail: "Example search", category: "Search", destination: .go, activity: .none))
        }
        return Array(examples.prefix(count))
    }
}

enum Lighting {
    static func radiance(width: CGFloat, height: CGFloat, strength: Double, focus: CGFloat, selected: CGFloat) -> CGFloat {
        guard width > 0, height > 0 else { return 0 }
        return 0.48 * CGFloat(strength) * (0.66 + 0.34 * focus) * (1 + 0.30 * selected)
            * width * height / ((width / 2 + 20) * (height + 20))
    }
}

struct ScopeLayout {
    // Selected labels borrow available space from adjacent tabs, then farther tabs.
    static func frames(width: CGFloat, bodyTop: CGFloat, config: Configuration,
                       reveal: CGFloat, weights: [CGFloat], labelWidths: [CGFloat]) -> [CGRect] {
        let count = weights.count
        guard count > 1 else { return [] }
        let geometry = ProductionContract.geometry[config.scopeReveal]
        let inset: CGFloat = config.scopeWidth == 0 ? 0 : 24
        let gap = min(8, max(0, (width - 2 * inset) / CGFloat(count) / 3))
        let span = max(0, width - 2 * inset - CGFloat(count - 1) * gap)
        let item = config.scopeWidth == 1 ? min(38, span / CGFloat(count)) : span / CGFloat(count)
        let minimum = min(24, span / CGFloat(count))
        var labels = zip(weights, labelWidths).map { $0 * $1 * reveal }
        let budget = max(0, span - min(16, span / CGFloat(count)) * CGFloat(count))
        var total = labels.reduce(0, +)
        if total > budget && total > 0 { labels = labels.map { $0 * budget / total }; total = budget }
        let donor = CGFloat(count - 1) * max(0, item - minimum)
        let free = max(0, span - item * CGFloat(count))
        if total > donor + free && total > 0 {
            labels = labels.map { $0 * (donor + free) / total }; total = donor + free
        }
        let growth = max(0, total - donor)
        var widths = labels.map { item + $0 }
        for index in 0..<count where labels[index] > 0 {
            var needed = labels[index] - (total > 0 ? growth * labels[index] / total : 0)
            for distance in 1..<count where needed > 0.001 {
                let neighbours = [index - distance, index + distance].filter { (0..<count).contains($0) }
                let capacities = neighbours.map { max(0, widths[$0] - minimum - labels[$0]) }
                let capacity = capacities.reduce(0, +)
                guard capacity > 0 else { continue }
                let take = min(needed, capacity)
                for (j, neighbour) in neighbours.enumerated() { widths[neighbour] -= take * capacities[j] / capacity }
                needed -= take
            }
        }
        let used = widths.reduce(0, +) + CGFloat(count - 1) * gap
        var x = config.scopeWidth == 1 ? (width - used) / 2 : inset
        let rise = geometry.restingRise + (geometry.revealedRise - geometry.restingRise) * reveal
        let height = geometry.restingHeight + (42 - geometry.restingHeight) * reveal
        return widths.map { width in
            defer { x += width + gap }
            return CGRect(x: x, y: bodyTop - rise, width: width, height: height)
        }
    }
}
