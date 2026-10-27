import XCTest
@testable import ArciumCommandBarStudio

final class StudioTests: XCTestCase {
    func testBrowserConfigurationRoundTripAndDisconnectedInvariant() {
        var config = Configuration()
        config.labels = 2; config.icons = 3; config.scopeReveal = 4; config.scopeWidth = 1
        config.resultCount = 20; config.connected = false; config.activityDots = false
        config.scopeTints = false; config.glowStrength = 1.6
        XCTAssertEqual(Configuration(config.dictionary), config)
        var dict = config.dictionary; dict["scope_width"] = 0
        XCTAssertEqual(Configuration(dict).scopeWidth, 2)
        dict["result_count"] = 100; dict["glow_strength"] = Double.infinity
        XCTAssertEqual(Configuration(dict).resultCount, 20)
        XCTAssertEqual(Configuration(dict).glowStrength, 0.75)
    }
    func testExamplesCoverEveryActivityAndDestination() {
        let rows = Fixture.rows(query: "", scope: 0, limit: 8)
        XCTAssertEqual(rows.first?.title, "Project notes")
        for activity: ExampleRow.Activity in [.none, .dot, .circle, .circleDot] {
            XCTAssertTrue(rows.contains { $0.activity == activity })
        }
        for destination: ExampleRow.Destination in [.go, .switchTab, .action] {
            XCTAssertTrue(rows.contains { $0.destination == destination })
        }
        XCTAssertEqual(Fixture.rows(query: "", scope: 0, limit: 20).count, 20)
    }
    func testSearchKeepsMatchingExamplesAndAnInertSearchAtLimit() {
        let rows = Fixture.rows(query: "PROJECT", scope: 0, limit: 2)
        XCTAssertEqual(rows.count, 2)
        XCTAssertTrue(rows[0].title.lowercased().contains("project"))
        XCTAssertEqual(rows[1].category, "Search")
        XCTAssertEqual(Fixture.rows(query: "zzzz", scope: 1, limit: 8).count, 1)
        XCTAssertEqual(Fixture.rows(query: "", scope: 3, limit: 8).first?.title, "YouTube · Project notes")
    }
    func testSmallEmittersDimAndFocusAndSelectionAreIndependent() {
        let baseline = Lighting.radiance(width: 80, height: 32, strength: 1, focus: 1, selected: 0)
        XCTAssertLessThan(Lighting.radiance(width: 38, height: 2, strength: 1, focus: 1, selected: 0), baseline)
        XCTAssertEqual(Lighting.radiance(width: 80, height: 32, strength: 1, focus: 0, selected: 0) / baseline, 0.61, accuracy: 0.00001)
        XCTAssertEqual(Lighting.radiance(width: 80, height: 32, strength: 1, focus: 1, selected: 1) / baseline, 1.51, accuracy: 0.00001)
        XCTAssertEqual(Lighting.radiance(width: 80, height: 0, strength: 1, focus: 1, selected: 1), 0)
    }
    func testNearestNeighboursDonateWithoutMovingDistantEdges() {
        var config = Configuration(); config.scopeWidth = 2; config.scopeReveal = 0
        let labels: [CGFloat] = [40, 40, 40, 40, 40, 40]
        let before = ScopeLayout.frames(width: 700, bodyTop: 48, config: config, reveal: 1, weights: [0, 0, 0, 0, 0, 0], labelWidths: labels)
        let after = ScopeLayout.frames(width: 700, bodyTop: 48, config: config, reveal: 1, weights: [0, 0, 1, 0, 0, 0], labelWidths: labels)
        XCTAssertEqual(after[2].width, before[2].width + 40, accuracy: 0.0001)
        XCTAssertEqual(after[1].width, before[1].width - 20, accuracy: 0.0001)
        XCTAssertEqual(after[3].width, before[3].width - 20, accuracy: 0.0001)
        XCTAssertEqual(after[0], before[0]); XCTAssertEqual(after[5], before[5])
    }
    func testEveryRevealAndWidthHasNonOverlappingFiniteGeometry() {
        for reveal in 0...5 { for width in 0...2 { for size: CGFloat in [280, 700] {
            var config = Configuration(); config.scopeReveal = reveal; config.scopeWidth = width
            let frames = ScopeLayout.frames(width: size, bodyTop: 48, config: config, reveal: 0.5, weights: [0.5, 0, 0, 0, 0.5, 0], labelWidths: [100, 100, 100, 100, 100, 100])
            XCTAssertEqual(frames.count, 6)
            for frame in frames { XCTAssertGreaterThanOrEqual(frame.width, 0); XCTAssertGreaterThanOrEqual(frame.minX, -0.001); XCTAssertLessThanOrEqual(frame.maxX, size + 0.001) }
            for (left, right) in zip(frames, frames.dropFirst()) { XCTAssertLessThanOrEqual(left.maxX, right.minX) }
        } } }
    }
}
