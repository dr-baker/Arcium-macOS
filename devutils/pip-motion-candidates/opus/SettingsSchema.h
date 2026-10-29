#pragma once

#import <Foundation/Foundation.h>
#include "Motion.hpp"

namespace pip_motion {

struct PreparedSettings {
  NSDictionary *values;
  bool rewrite;
};

inline bool settingsNumber(id value, double low, double high) {
  return [value isKindOfClass:NSNumber.class] &&
      CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID() &&
      std::isfinite([value doubleValue]) && [value doubleValue] >= low && [value doubleValue] <= high;
}

// Version 1 used both pointer points and percentages without a units marker.
// Preserve uniquely percentage values; retain ambiguous originals before resetting.
inline std::optional<PreparedSettings> prepareSettings(id object) {
  if (![object isKindOfClass:NSDictionary.class]) return std::nullopt;
  NSDictionary *input = object;
  id version = input[@"version"];
  if (!settingsNumber(version, 1, 2) ||
      ([version doubleValue] != 1 && [version doubleValue] != 2)) return std::nullopt;
  id dock = input[@"press_dock"], tuck = input[@"press_tuck"];
  const bool legacy = [version doubleValue] == 1;
  if ((dock && !settingsNumber(dock, 0, legacy ? 60 : 20)) ||
      (tuck && !settingsNumber(tuck, 2, legacy ? 300 : 40))) return std::nullopt;
  if (!legacy) return PreparedSettings{input, false};
  const bool percentage = tuck && [tuck doubleValue] < 40 &&
      (!dock || [dock doubleValue] <= 20);
  if (tuck && [tuck doubleValue] < 40 && dock && [dock doubleValue] > 20)
    return std::nullopt;  // Valid in neither known version-1 format.
  NSMutableDictionary *converted = [input mutableCopy];
  converted[@"version"] = @2;
  if (!percentage) {
    if (dock || tuck) {
      NSMutableDictionary *originals = [@{@"units":@"unmarked-version-1"} mutableCopy];
      if (dock) originals[@"press_dock"] = dock;
      if (tuck) originals[@"press_tuck"] = tuck;
      converted[@"legacy_press_thresholds"] = originals;
    }
    converted[@"press_dock"] = @(Settings{}.press_dock);
    converted[@"press_tuck"] = @(Settings{}.press_tuck);
  }
  return PreparedSettings{converted, true};
}

}  // namespace pip_motion
