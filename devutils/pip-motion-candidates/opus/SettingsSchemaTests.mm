#include "SettingsSchema.h"
#include <cstdlib>
#include <iostream>

using namespace pip_motion;
static int checks = 0;
static void check(bool condition, const char *name) {
  if (!condition) { std::cerr << "FAIL " << name << '\n'; std::exit(1); }
  ++checks;
  std::cout << "PASS " << name << '\n';
}
int main() {
  @autoreleasepool {
    auto old = prepareSettings(@{@"version":@1, @"press_dock":@20, @"press_tuck":@40});
    check(old && old->rewrite && [old->values[@"version"] isEqual:@2] &&
        [old->values[@"press_dock"] isEqual:@2.4] && [old->values[@"press_tuck"] isEqual:@24.7],
        "ambiguous version-1 thresholds reset once to explicit percentage defaults");
    check([old->values[@"legacy_press_thresholds"][@"press_dock"] isEqual:@20] &&
        [old->values[@"legacy_press_thresholds"][@"press_tuck"] isEqual:@40],
        "ambiguous original values remain in the migrated document");
    auto current = prepareSettings(@{@"version":@1, @"press_dock":@2, @"press_tuck":@26.23});
    check(current && current->rewrite && [current->values[@"press_tuck"] isEqual:@26.23],
        "Daniel's uniquely percentage tuning survives version migration");
    auto marked = prepareSettings(@{@"version":@2, @"press_dock":@20, @"press_tuck":@40});
    check(marked && !marked->rewrite && [marked->values[@"press_tuck"] isEqual:@40],
        "marked percentage cutoff remains unchanged");
    check(!prepareSettings(@{@"version":@2, @"press_tuck":@41}), "marked out-of-range percentage rejected");
    for (NSNumber *version in @[@1, @2]) {
      check(!prepareSettings(@{@"version":version, @"press_dock":@"bad", @"press_tuck":@41}),
          "malformed threshold cannot disappear during migration");
      check(!prepareSettings(@{@"version":version, @"press_dock":@YES}), "boolean threshold rejected");
    }
    check(!prepareSettings(@{@"version":@YES}), "boolean version rejected");
    check(!prepareSettings(@{@"version":@1.5}) && !prepareSettings(@{@"version":@3}), "unknown versions rejected");
    check(!prepareSettings(@{@"version":@1, @"press_dock":@30, @"press_tuck":@26}),
        "threshold combination invalid in both legacy formats rejected");
    auto partial = prepareSettings(@{@"version":@1, @"press_dock":@10});
    check(partial && [partial->values[@"legacy_press_thresholds"][@"press_dock"] isEqual:@10],
        "partial ambiguous input backed up before reset");
    auto empty = prepareSettings(@{@"version":@1});
    check(empty && [empty->values[@"press_tuck"] isEqual:@24.7], "missing legacy thresholds use defaults");
    check(prepareSettings(@{@"version":@2}).has_value(), "percentage thresholds remain optional");
    auto repeated = prepareSettings(old->values);
    check(repeated && !repeated->rewrite &&
        [repeated->values[@"legacy_press_thresholds"] isEqual:old->values[@"legacy_press_thresholds"]],
        "migration is idempotent and keeps the original record");
    auto historical = prepareSettings(@{@"version":@1, @"press_dock":@60, @"press_tuck":@300});
    check(historical && [historical->values[@"press_tuck"] isEqual:@24.7], "old pointer range migrates explicitly");
    check(!prepareSettings(@{@"version":@1, @"press_tuck":@301}), "invalid legacy range rejected before migration");
    std::cout << checks << " schema checks passed\n";
  }
}
