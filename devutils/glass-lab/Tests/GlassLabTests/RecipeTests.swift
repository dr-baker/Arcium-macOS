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
    func testReferenceUsesItsOwnScrimAndFreezesShaderScene() throws {
        let name = "GlassLabTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let store = LabStore(defaults: defaults)
        store.document.preview = .peek
        store.document.recipe.scrimDim = 0.7
        store.document.recipe.material = .glassmorphic
        store.pin()
        store.document.recipe.scrimDim = 0.1
        store.document.recipe.material = .systemLiquid
        store.document.moving = true
        store.showingReference = true
        XCTAssertEqual(store.sceneDocument.recipe.scrimDim, 0.7)
        XCTAssertFalse(store.sceneDocument.moving)
        store.showingReference = false
        XCTAssertEqual(store.sceneDocument.recipe.scrimDim, 0.1)
        XCTAssertTrue(store.sceneDocument.moving)
    }
}
