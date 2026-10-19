import XCTest
@testable import ArciumGlassLab

final class RecipeTests: XCTestCase {
    func testMaterialCompatibilityAndNativeMapping() {
        XCTAssertEqual(Material.liquid.title, "Clear")
        XCTAssertEqual(Material.systemLiquid.title, "Liquid")
        XCTAssertEqual(Material.liquid.rawValue, "liquid")
        XCTAssertEqual(Material.systemLiquid.rawValue, "systemLiquid")
        XCTAssertEqual(Set(Material.allCases.map(\.nativeCode)).count, Material.allCases.count)
    }
    func testFrostedRetainsSavedTint() throws {
        var recipe = Recipe(); recipe.tint = 0.8; recipe.material = .frosted
        XCTAssertEqual(recipe.effectiveTint, 0)
        let decoded = try JSONDecoder().decode(Recipe.self, from: JSONEncoder().encode(recipe))
        XCTAssertEqual(decoded.tint, 0.8)
        recipe.material = .systemLiquid
        XCTAssertEqual(recipe.effectiveTint, 0.8)
    }
    func testRecipeRoundTripAndBrowserTuning() throws {
        var document = LabDocument(); document.recipe.material = .glassmorphic
        document.recipe.windowTint = false; document.recipe.tintColor = RGB("#FF8040")
        document.reference = Recipe(); document.preview = .mru
        XCTAssertEqual(try JSONDecoder().decode(LabDocument.self, from: JSONEncoder().encode(document)), document)
        let tuning = document.recipe.productionTuning(windowColor: document.windowColor)
        XCTAssertEqual(tuning["panelMaterial"] as? String, "glassmorphic")
        XCTAssertEqual(tuning["panelTintColor"] as? String, "#FF8040")
        XCTAssertEqual(tuning["panelBlur"] as? Double, 9)
        XCTAssertNil(tuning["refraction"], "Lab-only shader controls must not masquerade as browser preferences")
    }
    func testImportedNumbersAreBounded() {
        var recipe = Recipe(); recipe.tint = -4; recipe.radius = 800; recipe.textSize = 0
        recipe.blur = .infinity; recipe.dispersion = .nan
        let bounded = recipe.clamped()
        XCTAssertEqual(bounded.tint, 0); XCTAssertEqual(bounded.radius, 48)
        XCTAssertEqual(bounded.textSize, 11); XCTAssertEqual(bounded.blur, 9)
        XCTAssertEqual(bounded.dispersion, 0.15)
    }
    @MainActor
    func testPersistenceAndReferenceAreSeparateFromBrowserSettings() throws {
        let name = "GlassLabTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let store = LabStore(defaults: defaults)
        store.document.recipe.tint = 0.7; store.pin()
        store.document.recipe.material = .frosted
        let reopened = LabStore(defaults: defaults)
        XCTAssertEqual(reopened.document.recipe.material, .frosted)
        XCTAssertEqual(reopened.document.reference?.tint, 0.7)
        XCTAssertEqual(reopened.document.reference?.material, .systemLiquid)
        reopened.swap()
        XCTAssertEqual(reopened.document.recipe.material, .systemLiquid)
        XCTAssertEqual(reopened.document.reference?.material, .frosted)
    }
    @MainActor
    func testChromiumUsesProductionTwoPassSigma() {
        XCTAssertEqual(ShaderRenderer.sigma(extraBlur: 9), sqrt(141), accuracy: 0.00001)
        XCTAssertEqual(ShaderRenderer.sigma(extraBlur: 0), sqrt(60), accuracy: 0.00001)
        XCTAssertEqual(Recipe().refraction, 7)
        XCTAssertEqual(Recipe().dispersion, 0.15)
    }
    @MainActor
    func testReferenceUsesItsOwnScrimAndKeepsSharedPlayback() throws {
        let name = "GlassLabTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let store = LabStore(defaults: defaults)
        defer { store.stopAnimation() }
        store.document.preview = .peek
        store.document.recipe.scrimDim = 0.7
        store.document.recipe.material = .glassmorphic
        store.pin()
        store.document.recipe.scrimDim = 0.1
        store.document.recipe.material = .systemLiquid
        store.document.moving = true
        store.showingReference = true
        XCTAssertEqual(store.sceneDocument.recipe.scrimDim, 0.7)
        XCTAssertTrue(store.sceneDocument.moving)
        store.showingReference = false
        XCTAssertEqual(store.sceneDocument.recipe.scrimDim, 0.1)
        XCTAssertTrue(store.sceneDocument.moving)
    }
    func testScrollMovesDownAndReturnsToTop() {
        XCTAssertEqual(BackgroundScroll.offset(phase: 0, viewport: 600, content: 1200), 0, accuracy: 0.001)
        XCTAssertEqual(BackgroundScroll.offset(phase: 0.25, viewport: 600, content: 1200), 300, accuracy: 0.001)
        XCTAssertEqual(BackgroundScroll.offset(phase: 0.5, viewport: 600, content: 1200), 600, accuracy: 0.001)
        XCTAssertEqual(BackgroundScroll.offset(phase: 0.75, viewport: 600, content: 1200), 300, accuracy: 0.001)
        XCTAssertEqual(BackgroundScroll.offset(phase: 1, viewport: 600, content: 1200), 0, accuracy: 0.001)
    }
    func testSolidBaseAndIntensityFollowAppearance() {
        var recipe = Recipe(); recipe.tint = 0
        XCTAssertEqual(recipe.solidColor(dark: true, tint: RGB("#FF0000")), RGB("#1D1E1C"))
        XCTAssertEqual(recipe.solidColor(dark: false, tint: RGB("#FF0000")), RGB("#F2F2F0"))
        XCTAssertEqual(recipe.intensity, 0)
        recipe.neutralIntensity = 3
        XCTAssertEqual(recipe.clamped().intensity, 1)
        recipe.neutralIntensity = .nan
        XCTAssertEqual(recipe.clamped().intensity, 0)
        XCTAssertNil(recipe.productionTuning(windowColor: RGB("#FFFFFF"))["neutralIntensity"])
    }
    func testOlderRecipesStillDecode() throws {
        var document = LabDocument(); document.recipe.tint = 0.65; document.preview = .mru
        var fields = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(document)) as? [String: Any])
        for key in ["backgroundAssetID", "backgroundAssetName", "backgroundImageData", "backgroundSpeed", "backgroundPhase"] { fields.removeValue(forKey: key) }
        let decoded = try JSONDecoder().decode(LabDocument.self, from: JSONSerialization.data(withJSONObject: fields))
        XCTAssertEqual(decoded.recipe.tint, 0.65)
        XCTAssertEqual(decoded.preview, .mru)
        XCTAssertEqual(decoded.playbackSpeed, 1)
        XCTAssertNil(decoded.backgroundImageData)
    }
    @MainActor
    func testPauseAndImagePreferenceStorage() throws {
        let name = "GlassLabTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        var document = LabDocument(); document.backgroundPhase = 0.4
        defaults.set(try JSONEncoder().encode(document), forKey: "lab-document-v1")
        let store = LabStore(defaults: defaults)
        defer { store.stopAnimation() }
        store.setPlaying(true); store.setPlaying(false)
        XCTAssertEqual(store.phase, 0.4)
        XCTAssertFalse(store.document.moving)
        store.document.backgroundImageData = Data([1, 2, 3])
        let saved = try JSONDecoder().decode(LabDocument.self, from: XCTUnwrap(defaults.data(forKey: "lab-document-v1")))
        XCTAssertNil(saved.backgroundImageData)
        XCTAssertEqual(saved.backgroundPhase, 0.4)
    }
}
