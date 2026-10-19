import SwiftUI

struct LabView: View {
    @ObservedObject var store: LabStore
    let controller: PanelController
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 18) {
                Text("Glass Lab").font(.system(size: 17, weight: .semibold))
                Picker("Preview", selection: Binding(get: { store.document.preview }, set: {
                    store.document.preview = $0
                    store.panelVisible = true
                    store.selectedItem = 0
                })) {
                    ForEach(Preview.allCases) { Label($0.title, systemImage: $0.icon).tag($0) }
                }.labelsHidden().frame(width: 170).accessibilityIdentifier("lab-preview")
                Spacer()
                if store.document.reference != nil {
                    Picker("Compare", selection: $store.showingReference) {
                        Text("Live").tag(false); Text("Reference").tag(true)
                    }.labelsHidden().pickerStyle(.segmented).frame(width: 165).accessibilityIdentifier("lab-compare")
                    Button(action: store.swap) { Image(systemName: "arrow.left.arrow.right") }.help("Swap live and reference")
                }
                Button("Pin reference", action: store.pin).accessibilityIdentifier("lab-pin")
                Button { store.panelVisible.toggle() } label: { Image(systemName: store.panelVisible ? "eye" : "eye.slash") }
                    .help("Show or hide the preview. Escape hides it.").accessibilityIdentifier("lab-visibility")
                Menu {
                    Button("Copy browser tuning", action: store.copyTuning)
                    Button("Export recipe…", action: store.export)
                    Button("Import recipe…", action: store.load)
                    Divider()
                    Button("Reset material", action: store.reset)
                    if store.document.reference != nil { Button("Remove reference") { store.showingReference = false; store.document.reference = nil } }
                } label: { Image(systemName: "ellipsis.circle") }.menuStyle(.borderlessButton).frame(width: 23)
            }
            .buttonStyle(.borderless).padding(.horizontal, 20).frame(height: 56)
            Divider()
            HStack(spacing: 0) {
                StageScene(document: store.sceneDocument, scrimVisible: store.panelVisible)
                    .background(StageAnchor(controller: controller))
                    .overlay(alignment: .bottomLeading) {
                        HStack(spacing: 7) {
                            Circle().fill(store.showingReference ? .orange : .green).frame(width: 6, height: 6)
                            Text(store.showingReference ? "Reference" : "Live")
                            Text(store.displayedRecipe.material.title).foregroundStyle(.secondary)
                        }
                        .font(.system(size: 11, weight: .medium)).padding(.horizontal, 12).padding(.vertical, 7)
                        .background(.regularMaterial, in: Capsule()).padding(14)
                    }
                Divider()
                inspector.frame(width: 310)
            }
            Divider()
            HStack {
                Text(store.status.isEmpty ? "⌘L command bar   ⌃Tab switcher   Esc hide" : store.status)
                Spacer()
                Text(store.displayedRecipe.material == .glassmorphic ? "Metal shader preview · simulated compositor" : "Production native renderers · simulated browser")
                    .foregroundStyle(.secondary)
            }.font(.system(size: 11)).padding(.horizontal, 16).frame(height: 28)
        }
        .frame(minWidth: 1140, minHeight: 760)
        .background(Color(nsColor: .windowBackgroundColor))
        .environment(\.colorScheme, store.document.dark ? .dark : .light)
    }

    private var inspector: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Material").font(.system(size: 13, weight: .semibold))
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 7) {
                        ForEach(Material.allCases) { material in
                            Button {
                                store.document.recipe.material = material
                                store.panelVisible = true
                            } label: {
                                HStack {
                                    Text(material == .glassmorphic ? "Chromium" : material.title)
                                    Spacer(minLength: 1)
                                    if store.document.recipe.material == material { Image(systemName: "checkmark").font(.system(size: 10, weight: .bold)) }
                                }
                                .font(.system(size: 12, weight: .medium)).padding(.horizontal, 10).frame(height: 33)
                                .background(store.document.recipe.material == material ? Color.accentColor.opacity(0.18) : Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 7))
                                .overlay(RoundedRectangle(cornerRadius: 7).stroke(store.document.recipe.material == material ? Color.accentColor.opacity(0.65) : .clear))
                            }.buttonStyle(.plain).accessibilityIdentifier("lab-material-\(material.rawValue)")
                        }
                    }
                    Text(store.document.recipe.material.explanation).font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    if store.document.preview == .controls || store.document.preview == .window {
                        Text(store.document.preview == .controls
                             ? "Try panel materials in 40 pt buttons. Browser controls use a separate shader."
                             : "Try panel materials in a window. Browser frame glow and grain are separate.")
                            .font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                }
                Divider()
                if store.document.recipe.material != .frosted {
                    VStack(alignment: .leading, spacing: 13) {
                        slider("Tint", value: $store.document.recipe.tint, range: 0...1, id: "lab-tint", percentage: true)
                        Toggle("Use window tint", isOn: $store.document.recipe.windowTint).toggleStyle(.switch).controlSize(.small)
                            .accessibilityIdentifier("lab-window-tint")
                        if !store.document.recipe.windowTint {
                            ColorPicker("Tint color", selection: colorBinding(\.tintColor), supportsOpacity: false).accessibilityIdentifier("lab-tint-color")
                        }
                    }
                    Divider()
                }
                VStack(alignment: .leading, spacing: 13) {
                    slider("Base intensity", value: Binding(get: { store.document.recipe.intensity }, set: { store.document.recipe.neutralIntensity = $0 }),
                           range: 0...1, id: "lab-intensity", percentage: true)
                        .help("Adds neutral light or dark backing independently of theme tint. 0% keeps the native material; 100% is opaque.")
                    if store.document.preview != .controls {
                        slider("Corner radius", value: $store.document.recipe.radius, range: 0...48, id: "lab-radius")
                    }
                    Toggle("Shadow", isOn: $store.document.recipe.shadow).toggleStyle(.switch).controlSize(.small)
                        .accessibilityIdentifier("lab-shadow")
                    ColorPicker("Selection & icons", selection: colorBinding(\.accent), supportsOpacity: false).accessibilityIdentifier("lab-accent")
                    HStack {
                        Text("Text")
                        Picker("Text color", selection: Binding(get: { store.document.recipe.ink ?? .automatic }, set: {
                            store.document.recipe.ink = $0 == .automatic ? nil : $0
                        })) {
                            ForEach(InkStyle.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                        }.labelsHidden().pickerStyle(.segmented).accessibilityIdentifier("lab-ink")
                    }
                }
                if store.document.preview == .mru {
                    Divider()
                    VStack(alignment: .leading, spacing: 13) {
                        Text("Tab labels").fontWeight(.semibold)
                        slider("Item backing", value: $store.document.recipe.itemBacking, range: 0...0.6, id: "lab-item-backing", percentage: true)
                        slider("Text size", value: $store.document.recipe.textSize, range: 11...22, id: "lab-text-size")
                        slider("Text shadow", value: $store.document.recipe.textShadow, range: 0...1, id: "lab-text-shadow", percentage: true)
                    }
                }
                if store.document.preview == .peek {
                    Divider()
                    VStack(alignment: .leading, spacing: 13) {
                        Text("Peek backdrop").fontWeight(.semibold)
                        slider("Dim", value: $store.document.recipe.scrimDim, range: 0...0.8, id: "lab-scrim-dim", percentage: true)
                        slider("Blur", value: $store.document.recipe.scrimBlur, range: 0...30, id: "lab-scrim-blur")
                    }
                }
                if store.document.recipe.material == .glassmorphic {
                    Divider()
                    VStack(alignment: .leading, spacing: 13) {
                        Text("Chromium shader").fontWeight(.semibold)
                        slider("Extra blur", value: $store.document.recipe.blur, range: 0...30, id: "lab-blur")
                        DisclosureGroup("Refraction & light") {
                            VStack(spacing: 13) {
                                slider("Refraction", value: $store.document.recipe.refraction, range: 0...40, id: "lab-refraction")
                                slider("Edge width", value: $store.document.recipe.edge, range: 1...80, id: "lab-edge")
                                slider("Dispersion", value: $store.document.recipe.dispersion, range: 0...1, id: "lab-dispersion", percentage: true)
                                slider("Specular", value: $store.document.recipe.specular, range: 0...1, id: "lab-specular", percentage: true)
                                slider("Grain", value: $store.document.recipe.grain, range: 0...0.1, id: "lab-grain", percentage: true)
                            }.padding(.top, 12)
                        }
                    }
                }
                Divider()
                VStack(alignment: .leading, spacing: 13) {
                    Text("Behind the glass").fontWeight(.semibold)
                    Picker("Page", selection: $store.document.backdrop) { ForEach(Backdrop.allCases) { Text($0.title).tag($0) } }
                        .accessibilityIdentifier("lab-backdrop")
                    ColorPicker("Window color", selection: Binding(get: { store.document.windowColor.color }, set: { store.document.windowColor = RGB($0) }), supportsOpacity: false)
                        .accessibilityIdentifier("lab-window-color")
                    Toggle("Dark page", isOn: $store.document.dark).toggleStyle(.switch).controlSize(.small).accessibilityIdentifier("lab-dark")
                    Toggle("Animate page", isOn: $store.document.moving).toggleStyle(.switch).controlSize(.small)
                        .disabled(store.document.recipe.material == .glassmorphic)
                        .accessibilityIdentifier("lab-animate")
                    if store.document.recipe.material == .glassmorphic { Text("Shader mode uses a still backdrop. Native modes sample the live page.").font(.system(size: 11)).foregroundStyle(.secondary) }
                }
                Divider()
                DisclosureGroup("Appearance override") {
                    Picker("Activity", selection: $store.activeAppearance) {
                        Text("Production default").tag(0); Text("Active").tag(1); Text("Inactive").tag(2)
                    }.padding(.top, 8).accessibilityIdentifier("lab-activity")
                }
                HStack {
                    Button("Copy tuning", action: store.copyTuning).accessibilityIdentifier("lab-copy")
                    Spacer(); Button("Reset", action: store.reset).accessibilityIdentifier("lab-reset")
                }.padding(.top, 4)
                if store.showingReference { Text("Showing the pinned reference. Switch to Live to edit.").font(.system(size: 11)).foregroundStyle(.secondary) }
            }
            .font(.system(size: 12)).padding(20)
            .disabled(store.showingReference)
        }
    }
    private func colorBinding(_ path: WritableKeyPath<Recipe, RGB>) -> Binding<Color> {
        Binding(get: { store.document.recipe[keyPath: path].color }, set: { store.document.recipe[keyPath: path] = RGB($0) })
    }
    private func slider(_ label: String, value: Binding<Double>, range: ClosedRange<Double>, id: String, percentage: Bool = false) -> some View {
        VStack(spacing: 7) {
            HStack {
                Text(label); Spacer()
                Text(percentage ? "\(Int(value.wrappedValue*100))%" : "\(Int(value.wrappedValue)) pt")
                    .monospacedDigit().foregroundStyle(.secondary)
            }
            Slider(value: value, in: range).controlSize(.small).accessibilityLabel(label).accessibilityIdentifier(id)
        }
    }
}
