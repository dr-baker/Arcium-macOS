import SwiftUI

struct PanelContent: View {
    @ObservedObject var store: LabStore
    var recipe: Recipe
    @State private var query = ""
    private var accent: Color { recipe.accent.color }
    private var ink: Color {
        if recipe.ink == .light { return .white }
        if recipe.ink == .dark { return .black }
        if recipe.material == .glassmorphic { return store.document.dark ? .white : .black }
        let tint = recipe.windowTint ? store.document.windowColor : recipe.tintColor
        let alpha = recipe.effectiveTint
        let luminance = (tint.red * 0.2126 + tint.green * 0.7152 + tint.blue * 0.0722) * alpha + 0.115 * (1-alpha)
        return luminance > 0.38 ? Color(red: 0.08, green: 0.09, blue: 0.1) : .white
    }
    var body: some View {
        Group {
            switch store.document.preview {
            case .command: command
            case .mru: mru
            case .peek: peek
            case .controls: controls
            case .window: windowChrome
            }
        }
        .foregroundStyle(ink)
        .tint(accent)
        .environment(\.colorScheme, store.document.dark ? .dark : .light)
    }
    private var command: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "magnifyingglass").font(.system(size: 15))
                TextField("Search tabs, Pins, Favorites and the web", text: $query)
                    .textFieldStyle(.plain).font(.system(size: 18, weight: .medium))
                    .accessibilityIdentifier("lab-command-query")
            }.padding(.horizontal, 22).frame(height: 60)
            Divider().overlay(ink.opacity(0.1)).padding(.horizontal, 12)
            VStack(spacing: 2) {
                ForEach(Array(sampleTabs.enumerated()), id: \.offset) { index, tab in
                    Button { store.selectedItem = index } label: {
                        HStack(spacing: 12) {
                            Image(systemName: index == 3 ? "circle.fill" : "circle").font(.system(size: 9)).foregroundStyle(accent)
                            SiteIcon(index: index, size: 18)
                            Text(tab.0).font(.system(size: 14, weight: .semibold))
                            Text(tab.1).font(.system(size: 10)).foregroundStyle(accent)
                            Spacer()
                            if store.selectedItem == index { Text("Switch").font(.system(size: 12, weight: .medium)) }
                            Image(systemName: index == 3 ? "arrow.turn.down.left" : "arrow.up.right").foregroundStyle(accent)
                        }
                        .padding(.horizontal, 12).frame(height: 42)
                        .background(store.selectedItem == index ? accent.opacity(0.27) : .clear, in: RoundedRectangle(cornerRadius: 6))
                        .contentShape(Rectangle())
                    }.buttonStyle(.plain)
                        .onHover { hover in if hover { store.selectedItem = index } }
                        .accessibilityIdentifier("lab-command-row-\(index)")
                }
            }.padding(8)
            Spacer(minLength: 0)
            Divider().padding(.horizontal, 12)
            HStack {
                Text("← → / Tab scopes · ↑ ↓ choose ↵ switch")
                Spacer(); Text("Actions  ⌘K")
            }.font(.system(size: 11)).opacity(0.65).padding(.horizontal, 18).frame(height: 34)
        }
    }
    private var mru: some View {
        HStack(spacing: 10) {
            ForEach(0..<3) { index in
                Button { store.selectedItem = index } label: {
                    VStack(alignment: .leading, spacing: 10) {
                        thumbnail(index).frame(height: 142).clipShape(RoundedRectangle(cornerRadius: 8))
                        HStack(spacing: 8) {
                            SiteIcon(index: index, size: 17)
                            Text(sampleTabs[index].0).font(.system(size: recipe.textSize, weight: .medium))
                                .lineLimit(1)
                                .shadow(color: .black.opacity(recipe.textShadow), radius: 2, y: 1)
                        }.padding(.horizontal, 3)
                    }
                    .padding(10)
                    .background(.black.opacity(recipe.itemBacking), in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(store.selectedItem % 3 == index ? accent : .clear, lineWidth: 2))
                }.buttonStyle(.plain).onHover { if $0 { store.selectedItem = index } }
                    .accessibilityIdentifier("lab-mru-item-\(index)")
            }
        }.padding(12)
    }
    @ViewBuilder
    private func thumbnail(_ index: Int) -> some View {
        if index == 0 {
            VStack(alignment: .leading, spacing: 12) {
                Text("M mdn_").font(.system(size: 12, weight: .semibold))
                Text("Resources for Developers,\nby Developers_").font(.system(size: 16, weight: .medium))
                Text("Documenting the web").font(.system(size: 8))
                RoundedRectangle(cornerRadius: 10).stroke(.gray.opacity(0.5)).frame(height: 15)
            }.padding(15).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .foregroundStyle(.white).background(Color(red: 0.1, green: 0.12, blue: 0.13))
        } else if index == 1 {
            Landscape(phase: 0.7).overlay(alignment: .bottomLeading) {
                Text("The art of the journey").font(.system(size: 16, weight: .bold, design: .serif)).foregroundStyle(.white).padding(12)
            }
        } else {
            VStack(alignment: .leading, spacing: 12) {
                Text("ars TECHNICA").font(.system(size: 18, weight: .bold))
                Rectangle().fill(.orange.gradient).frame(height: 44)
                Text("Science, technology and the future").font(.system(size: 11, weight: .bold))
            }.padding(12).frame(maxWidth: .infinity, maxHeight: .infinity).foregroundStyle(.white).background(.black)
        }
    }
    private var peek: some View {
        VStack(spacing: 0) {
            HStack {
                Label("fieldnotes.example", systemImage: "lock.fill").font(.system(size: 12))
                Spacer()
                Button {} label: { Image(systemName: "arrow.up.right.square") }.help("Open in tab")
                Button { store.panelVisible = false } label: { Image(systemName: "xmark") }.help("Close Peek")
            }.buttonStyle(.plain).padding(18)
            VStack(alignment: .leading, spacing: 20) {
                Landscape(phase: 0.4).frame(height: 200)
                Text("Light on the water").font(.system(size: 35, weight: .medium, design: .serif))
                Text("An observation of the small things that shape a place. Follow the shore, watch the light change, and let the day unfold.")
                    .font(.system(size: 15)).lineSpacing(5)
                Spacer()
            }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .foregroundStyle(store.document.dark ? .white : .black)
                .background(store.document.dark ? Color(white: 0.1) : .white)
                .clipShape(RoundedRectangle(cornerRadius: max(0, recipe.radius-4)))
                .padding([.horizontal, .bottom], 10)
        }
    }
    private var controls: some View {
        HStack(spacing: 26) {
            ForEach(["chevron.left", "chevron.right", "arrow.up.right.square", "pin", "xmark"], id: \.self) { icon in
                Button {} label: { Image(systemName: icon).font(.system(size: 20, weight: .medium)).frame(width: 40, height: 40) }
                    .buttonStyle(.plain).foregroundStyle(accent)
                    .help(icon == "xmark" ? "Close" : icon == "pin" ? "Pin" : "Navigate")
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
    private var windowChrome: some View {
        VStack(spacing: 0) {
            HStack {
                ForEach([Color.red, .yellow, .green], id: \.self) { Circle().fill($0).frame(width: 10, height: 10) }
                Spacer(); Text("arcium.example").font(.system(size: 12)); Spacer()
                Image(systemName: "square.and.arrow.up")
            }.padding(.horizontal, 18).frame(height: 44)
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 20) {
                    Label("Space", systemImage: "circle.fill").font(.system(size: 12, weight: .semibold))
                    ForEach(Array(sampleTabs.enumerated()), id: \.offset) { index, tab in
                        Label { Text(tab.0).font(.system(size: 11)) } icon: { SiteIcon(index: index, size: 14) }
                    }
                    Spacer()
                }.padding(16).frame(width: 150)
                BrowserPage(document: store.document).foregroundStyle(store.document.dark ? .white : .black)
                    .clipShape(RoundedRectangle(cornerRadius: 8)).padding([.trailing, .bottom], 5)
            }
        }
    }
}
