#!/usr/bin/env python3
"""Regenerate production design types from the core-owned parameter schema."""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path
import difflib
import json

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'helium-chromium'
SWIFT = 'chrome/browser/ui/cocoa/arcium_settings_swift/Sources/ArciumSettingsUI/ArciumCommandDesign.swift'
CORE_PATCH = CORE / 'patches/personal/arcium-command-design-tokens.patch'
MAC_PATCH = ROOT / 'patches/personal/arcium-command-design-tokens-macos.patch'


def module(core=CORE):
    spec = importlib.util.spec_from_file_location('command_design', core / 'devutils/command_design.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def swift(schema):
    # Renderer fields and editor descriptors come from the same schema. This
    # dictionary exists only in settings, never in the C++ rendering path.
    text = '''// Generated from core devutils/ui/command_bar_design.json. Do not edit.
import Foundation
import CoreFoundation

nonisolated struct ArciumCommandDesign: Equatable, Sendable {
    struct Token: Identifiable, Sendable {
        let id: String
        let label: String
        let group: String
        let initial: Double
        let range: ClosedRange<Double>
        let step: Double
        let integer: Bool
        let color: Bool
        let initialColor: String
    }
    static let tokens: [Token] = [
'''
    for t in schema['tokens']:
        color = t['type'] == 'color'
        text += (f'        .init(id: "{t["key"]}", label: "{t["label"]}", group: "{t["group"]}", '
                 f'initial: {t["default"] if not color else 0}, '
                 f'range: {t.get("min", 0)}...{t.get("max", 1)}, step: {t.get("step", 1)}, '
                 f'integer: {str(t["type"] == "int").lower()}, color: {str(color).lower()}, '
                 f'initialColor: {json.dumps(t["default"] if color else "")}),\n')
    text += '''    ]
    private var numbers: [String: Double] = [:]
    private var colors: [String: String] = [:]
    init() {}
    init?(dictionary: [String: Any]) {
        for (key, raw) in dictionary {
            guard let token = Self.tokens.first(where: { $0.id == key }) else { return nil }
            if token.color {
                guard let value = raw as? String,
                      value.isEmpty || (value.count == 7 && value.first == "#" &&
                          value.dropFirst().allSatisfy({ $0.isASCII && $0.isHexDigit })) else { return nil }
                if value.uppercased() != token.initialColor.uppercased() { colors[key] = value.uppercased() }
            } else {
                guard let value = raw as? NSNumber,
                      CFGetTypeID(value) != CFBooleanGetTypeID() else { return nil }
                let number = value.doubleValue
                guard number.isFinite, token.range.contains(number),
                      !token.integer || number.rounded(.towardZero) == number else { return nil }
                if number != token.initial { numbers[key] = number }
            }
        }
    }
    func number(_ token: Token) -> Double { numbers[token.id] ?? token.initial }
    func color(_ token: Token) -> String { colors[token.id] ?? token.initialColor }
    mutating func setNumber(_ value: Double, for token: Token) {
        guard !token.color, value.isFinite else { return }
        let bounded = min(token.range.upperBound, max(token.range.lowerBound, value))
        let normalized = token.integer ? bounded.rounded() : bounded
        numbers[token.id] = normalized == token.initial ? nil : normalized
    }
    mutating func setColor(_ value: String, for token: Token) {
        guard token.color, let parsed = Self(dictionary: [token.id: value]) else { return }
        colors[token.id] = parsed.colors[token.id]
    }
    var dictionary: [String: Any] {
        var result: [String: Any] = numbers
        for (key, value) in colors { result[key] = value }
        return result
    }
    var isDefault: Bool { numbers.isEmpty && colors.isEmpty }
}
'''
    return text


def added_section(path, text):
    return (f'Index: src/{path}\n' + '=' * 67 + '\n' +
            ''.join(difflib.unified_diff([], text.splitlines(keepends=True),
                                        fromfile='/dev/null', tofile='src/' + path)))


def replace_section(patch, path, text, check):
    data = patch.read_text()
    marker = 'Index: src/' + path + '\n'
    start = data.index(marker)
    end = data.find('\nIndex: ', start + len(marker))
    end = len(data) if end == -1 else end + 1
    generated = data[:start] + added_section(path, text) + data[end:]
    if check:
        if generated != data: raise ValueError(f'Stale generated production design type: {patch}')
    else:
        patch.write_text(generated)


def verify(root=ROOT):
    """Fail before compiling if a schema edit has not reached both languages."""
    core = module(root / 'helium-chromium'); value = core.schema()
    replace_section(root / CORE_PATCH.relative_to(ROOT), core.HEADER, core.cpp(value), True)
    replace_section(root / MAC_PATCH.relative_to(ROOT), SWIFT, swift(value), True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--authoring-root', type=Path)
    args = parser.parse_args()
    core = module(); schema = core.schema()
    outputs = [(CORE_PATCH, core.HEADER, core.cpp(schema)), (MAC_PATCH, SWIFT, swift(schema))]
    for patch, path, text in outputs:
        if args.authoring_root:
            output = args.authoring_root / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text)
        else:
            replace_section(patch, path, text, args.check)
    print('Production command-bar design types match the shared schema' if args.check else 'Generated production command-bar design types')


if __name__ == '__main__':
    main()
