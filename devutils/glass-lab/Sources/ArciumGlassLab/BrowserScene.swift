import SwiftUI

struct BrowserStage: View {
    let document: LabDocument
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 9) {
                ForEach([Color.red, .yellow, .green], id: \.self) { color in Circle().fill(color.opacity(0.9)).frame(width: 11, height: 11) }
                Image(systemName: "sidebar.left").padding(.horizontal, 10)
                Image(systemName: "chevron.left").foregroundStyle(.secondary)
                Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                HStack {
                    Image(systemName: "lock.fill").font(.system(size: 9))
                    Text(document.backdrop == .documentation ? "developer.mozilla.org" : "fieldnotes.example")
                    Spacer(); Image(systemName: "arrow.clockwise")
                }
                .font(.system(size: 12)).padding(.horizontal, 12).frame(height: 27)
                .background(.black.opacity(0.18), in: RoundedRectangle(cornerRadius: 7))
                Image(systemName: "square.and.arrow.up").padding(.horizontal, 8)
            }
            .padding(.horizontal, 16).frame(height: 44)
            HStack(spacing: 0) {
                sidebar.frame(width: 172)
                BrowserPage(document: document)
            }
        }
        .foregroundStyle(document.dark ? .white : .black)
        .background(document.windowColor.color.gradient)
        .clipped()
        .environment(\.colorScheme, document.dark ? .dark : .light)
    }
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 22) {
                Image(systemName: "globe"); Image(systemName: "chevron.left.forwardslash.chevron.right")
                Image(systemName: "play.rectangle.fill")
            }.padding(.bottom, 12)
            Label("Space", systemImage: "circle.fill").font(.system(size: 11, weight: .semibold))
            ForEach(Array(sampleTabs.enumerated()), id: \.offset) { index, tab in
                HStack(spacing: 8) {
                    SiteIcon(index: index, size: 14)
                    Text(tab.0).lineLimit(1)
                    Spacer(minLength: 0)
                }
                .font(.system(size: 12))
                .padding(8).background(index == 0 ? .black.opacity(0.23) : .clear, in: RoundedRectangle(cornerRadius: 6))
                .padding(.horizontal, -8)
            }
            Divider()
            Label("New tab", systemImage: "plus").font(.system(size: 12)).opacity(0.65)
            Spacer()
            HStack { Image(systemName: "slider.horizontal.3"); Spacer(); Image(systemName: "plus") }.opacity(0.7)
        }
        .padding(16).frame(maxHeight: .infinity)
        .background(.black.opacity(document.dark ? 0.32 : 0.04))
    }
}

let sampleTabs = [("MDN Web Docs", "Pin"), ("The Verge", "Pin"), ("Ars Technica", "Pin"), ("New Tab", "Tab"), ("YouTube", "Favorite")]

struct SiteIcon: View {
    var index: Int
    var size: Double = 18
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: index == 2 ? size : 3)
                .fill([Color.black, .purple, .orange, .gray.opacity(0.2), .red][index % 5])
            Text(["M", "V", "ars", "✳", "▶"][index % 5])
                .font(.system(size: size * (index == 2 ? 0.48 : 0.68), weight: .bold))
                .foregroundStyle(index == 3 ? Color.secondary : Color.white)
        }.frame(width: size, height: size)
    }
}

struct BrowserPage: View {
    let document: LabDocument
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 24, paused: !document.moving)) { context in
            GeometryReader { geometry in
                let phase = document.moving ? context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 30) / 30 : 0.28
                Group {
                    switch document.backdrop {
                    case .editorial: editorial(size: geometry.size, phase: phase)
                    case .documentation: documentation
                    case .contrast: contrast(phase: phase)
                    }
                }.frame(width: geometry.size.width, height: geometry.size.height, alignment: .topLeading).clipped()
            }
        }
        .background(document.dark ? Color(red: 0.105, green: 0.12, blue: 0.13) : Color.white)
    }
    private func editorial(size: CGSize, phase: Double) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Fieldnotes").font(.system(size: 28, weight: .semibold, design: .serif))
                Spacer()
                Text("Places     Architecture     Objects").font(.system(size: 11))
            }.padding(.horizontal, 34).frame(height: 72)
            ZStack(alignment: .bottomLeading) {
                Landscape(phase: phase).frame(height: max(320, size.height * 0.57))
                LinearGradient(colors: [.clear, .black.opacity(0.62)], startPoint: .center, endPoint: .bottom)
                VStack(alignment: .leading, spacing: 10) {
                    Text("A slower way of seeing").font(.system(size: 44, weight: .medium, design: .serif))
                    Text("An autumn journey through water, stone and open sky.").font(.system(size: 14))
                }.foregroundStyle(.white).padding(34)
            }.clipped()
            HStack(alignment: .top, spacing: 28) {
                ForEach(0..<3) { index in
                    VStack(alignment: .leading, spacing: 10) {
                        Rectangle().fill([Color.teal.opacity(0.65), .orange.opacity(0.65), .indigo.opacity(0.6)][index]).frame(height: 74)
                        Text(["Light on the water", "The architecture of quiet", "Objects worth keeping"][index])
                            .font(.system(size: 19, weight: .medium, design: .serif))
                        Text("Stories, observations and places to return to.").font(.system(size: 12)).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }.padding(30)
            Spacer(minLength: 0)
        }
    }
    private var documentation: some View {
        VStack(alignment: .leading, spacing: 25) {
            HStack {
                Text("M mdn_").font(.system(size: 25, weight: .medium))
                Spacer(); Text("HTML    CSS    JavaScript    Web APIs").font(.system(size: 12))
            }.padding(.vertical, 8)
            Divider()
            Text("Resources for Developers,\nby Developers_")
                .font(.system(size: 42, weight: .medium)).padding(.vertical, 30)
            Text("Documenting CSS, JavaScript and the web.").font(.system(size: 22))
            HStack { Image(systemName: "magnifyingglass"); Text("Search MDN"); Spacer(); Text("⌘ K").foregroundStyle(.secondary) }
                .padding(15).overlay(RoundedRectangle(cornerRadius: 24).stroke(.secondary.opacity(0.5)))
            Text("Featured articles").font(.system(size: 25, weight: .medium)).padding(.top, 15)
            ForEach(["A guide to modern CSS", "Making the web work for everyone", "JavaScript reference", "Web performance fundamentals"], id: \.self) { title in
                VStack(alignment: .leading, spacing: 10) {
                    Text(title).font(.system(size: 18, weight: .medium))
                    Text("Explore the technologies that build the web. Examples, tutorials and reference documentation.")
                        .font(.system(size: 13)).foregroundStyle(.secondary)
                }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(RoundedRectangle(cornerRadius: 5).stroke(.secondary.opacity(0.3)))
            }
            Spacer(minLength: 0)
        }.padding(.horizontal, 42)
    }
    private func contrast(phase: Double) -> some View {
        GeometryReader { geometry in
            Canvas { context, size in
                let tile = 44.0
                for y in 0...Int(size.height / tile) {
                    for x in 0...Int(size.width / tile) {
                        context.fill(Path(CGRect(x: Double(x) * tile, y: Double(y) * tile, width: tile, height: tile)), with: .color((x + y).isMultiple(of: 2) ? .white : .black))
                    }
                }
                for x in 0..<6 {
                    let rect = CGRect(x: Double(x) * size.width / 6, y: size.height * 0.36, width: size.width / 6, height: size.height * 0.3)
                    context.fill(Path(rect), with: .color([.red, .orange, .yellow, .green, .blue, .purple][x]))
                }
            }
            VStack(alignment: .leading, spacing: 26) {
                Text("Fine detail / 1 px / Aa").font(.system(size: 37, weight: .bold))
                Text(String(repeating: "Glass needs detail behind it. ", count: 18)).font(.system(size: 15))
                Spacer()
                Text("0123456789     Aa Bb Cc Dd").font(.system(size: 30, weight: .semibold))
            }
            .padding(28).foregroundStyle(.white).shadow(color: .black, radius: 1)
            .offset(x: document.moving ? sin(phase * .pi * 2) * 70 : 0)
        }
    }
}

struct Landscape: View {
    var phase: Double
    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            ZStack {
                LinearGradient(colors: [Color(red: 0.34, green: 0.62, blue: 0.7), Color(red: 0.91, green: 0.76, blue: 0.53)], startPoint: .top, endPoint: .bottom)
                Circle().fill(Color(red: 0.98, green: 0.89, blue: 0.69)).frame(width: 100, height: 100)
                    .position(x: size.width * (0.74 + sin(phase * .pi * 2) * 0.06), y: size.height * 0.24)
                ForEach(0..<5) { layer in
                    Path { path in
                        path.move(to: CGPoint(x: -10, y: size.height))
                        let width = Double(size.width)
                        let height = Double(size.height)
                        let layerIndex = Double(layer)
                        for step in 0...60 {
                            let x = Double(step) / 60 * (width + 20) - 10
                            let angle = x / width * (5 + layerIndex) + layerIndex * 2 + phase * 2
                            let wave = sin(angle)
                            let baseline = height * (0.40 + layerIndex * 0.11)
                            let amplitude = height * (0.13 - layerIndex * 0.013)
                            let y = baseline + wave * amplitude
                            path.addLine(to: CGPoint(x: x, y: y))
                        }
                        path.addLine(to: CGPoint(x: size.width + 10, y: size.height)); path.closeSubpath()
                    }
                    .fill([Color(red: 0.38, green: 0.47, blue: 0.48), Color(red: 0.25, green: 0.40, blue: 0.42), Color(red: 0.16, green: 0.33, blue: 0.34), Color(red: 0.10, green: 0.27, blue: 0.27), Color(red: 0.07, green: 0.19, blue: 0.2)][layer])
                }
                ForEach(0..<32) { index in
                    Rectangle().fill(.white.opacity(0.08))
                        .frame(width: size.width * (0.12 + Double(index % 4) * 0.04), height: 1)
                        .position(x: size.width * Double((index * 37) % 100) / 100, y: size.height * (0.78 + Double(index) * 0.006))
                }
            }
        }.clipped()
    }
}

struct StageScene: View {
    let document: LabDocument
    var scrimVisible = true
    var body: some View {
        BrowserStage(document: document)
            .blur(radius: document.preview == .peek && scrimVisible ? document.recipe.scrimBlur : 0)
            .overlay {
                if document.preview == .peek && scrimVisible {
                    Color.black.opacity(document.recipe.scrimDim).allowsHitTesting(false)
                }
            }
    }
}
