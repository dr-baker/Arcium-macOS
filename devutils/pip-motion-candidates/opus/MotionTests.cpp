#include "Motion.hpp"
#include <cstdlib>
#include <iostream>
#include <random>
#include <string>

using namespace pip_motion;
static int checks = 0;
static void check(bool condition, const std::string& name) {
  if (!condition) { std::cerr << "FAIL " << name << '\n'; std::exit(1); }
  ++checks;
  std::cout << "PASS " << name << '\n';
}
static bool near(double a, double b, double epsilon = 1e-7) {
  return std::abs(a - b) < epsilon;
}
static void finish(Motion& m) { for (int i = 0; i < 1200; ++i) m.step(1.0 / 120); }

int main() {
  Motion m;
  check(m.position.x == 668 && m.position.y == 12, "default bottom-right margin");
  auto origin = Point{600, 200};
  auto projected = m.dockTarget(origin, {-1200, 600});
  auto position_only = m.dockTarget(origin, {});
  check(projected.x == 12 && projected.y == 508 && position_only.x == 668,
        "release momentum can select a farther corner");
  m.throwFrom(origin, {-1200, 600}, false);
  finish(m);
  check(m.phase == Phase::Resting && m.position.x == 12 && m.position.y == 508,
        "throw settles exactly at projected corner");

  for (double damping : {0.65, 1.0, 1.35}) {
    double x = 250, v = -800;
    for (int i = 0; i < 1000; ++i) spring(x, v, 0, .4, damping, 1.0 / 120);
    check(near(x, 0) && near(v, 0), "spring converges damping=" + std::to_string(damping));
    double x1 = 250, v1 = -800, x2 = x1, v2 = v1;
    spring(x1, v1, 0, .4, damping, .2);
    for (int i = 0; i < 24; ++i) spring(x2, v2, 0, .4, damping, 1.0 / 120);
    check(near(x1, x2) && near(v1, v2), "spring is cadence independent damping=" + std::to_string(damping));
  }

  m.throwFrom({400, 100}, {800, 500}, false);
  m.step(.04);
  auto before = m.position;
  m.begin(before + Point{40, 20}, 1);
  check(near(m.position.x, before.x) && near(m.position.y, before.y),
        "re-grab starts at current presentation without a jump");
  m.drag(before + Point{90, 50}, 1.03);
  check(near(m.position.x, before.x + 50) && near(m.position.y, before.y + 30),
        "drag preserves the pointer-to-window offset");
  m.end(1.04);
  before = m.position;
  auto velocity = m.velocity;
  auto next = m.settings; next.response = .7; next.damping = .8;
  m.retune(next);
  check(near(m.position.x, before.x) && near(m.position.y, before.y) &&
        near(m.velocity.x, velocity.x) && near(m.velocity.y, velocity.y),
        "live spring tuning preserves position and velocity");

  VelocityTracker tracker;
  tracker.add({0, 0}, 1); tracker.add({50, 0}, 1.05);
  check(near(tracker.value(1.06).x, 1000) && tracker.value(1.2).x == 0,
        "release velocity expires after a pause");

  m = Motion{};
  m.throwFrom({300, 250}, {1800, 0}, true);
  check(m.tucked == Side::None, "a cross-screen flick does not accidentally stash");
  m.throwFrom({730, 200}, {1000, 0}, true);
  finish(m);
  check(m.phase == Phase::Tucked && m.position.x == 972 && m.position.y == 200,
        "edge fling leaves only the configured handle");
  m.restore();
  before = m.position; velocity = m.velocity;
  next = m.settings; next.response = .65;
  m.retune(next);
  check(near(m.position.x, before.x) && near(m.velocity.x, velocity.x) && m.target.y == 200,
        "retuning restore preserves its continuous path");
  finish(m);
  check(m.position.x == 668 && m.position.y == 200,
        "restore preserves the stash height");

  m.tuck(Side::Left); finish(m);
  auto start = m.position;
  m.begin(start + Point{310, 80}, 2);
  m.end(2.1);
  finish(m);
  check(m.tucked == Side::None && m.position.x == 12,
        "clicking a tucked window restores it");

  m.tuck(Side::Right); finish(m);
  start = m.position;
  m.begin(start + Point{14, 80}, 3);
  m.drag(start + Point{-36, 80}, 3.1);
  check(near(m.position.x, start.x - 50), "tucked pull-out tracks before release");
  m.end(3.11); finish(m);
  check(m.tucked == Side::None && m.position.x == 668, "inward pull restores the window");

  m.throwFrom({-100, 220}, {}, true);
  auto stash_start = m.position;
  check(stash_start.x == -100 && m.target.x == -292,
        "stash begins at release position without resetting the frame");
  finish(m);
  next = m.settings; next.handle = 44;
  m.retune(next); finish(m);
  check(m.position.x == -276, "handle width updates while tucked");

  next = m.settings; next.docking = Docking::SideEdges;
  m.restore(); finish(m); m.retune(next); finish(m);
  auto side = m.dockTarget({50, 210}, {0, 0});
  check(side.x == 12 && side.y == 210, "side-edge mode retains arbitrary vertical position");

  const double a = rubber(50, 180, .35), b = rubber(150, 180, .35);
  check(a > 0 && b > a && b < 150, "boundary resistance increases without hard clipping");

  m = Motion{};
  m.throwFrom({320, 230}, {35, 10}, true); finish(m);
  check(m.position.x == 320 && m.position.y == 230,
        "smart placement keeps a deliberate interior drop");
  m.throwFrom({320, 230}, {500, 100}, true); finish(m);
  check(m.position.x == 668 && m.position.y == 508,
        "smart placement docks a faster throw");
  m.throwFrom({640, 30}, {10, 0}, true); finish(m);
  check(m.position.x == 668 && m.position.y == 12,
        "smart placement attracts a slow drop near a corner");
  next = m.settings; next.snap_distance = 10; m.retune(next);
  m.throwFrom({640, 30}, {10, 0}, true); finish(m);
  check(m.position.x == 640 && m.position.y == 30,
        "snap distance is tunable independently of release speed");
  next.free_speed = 600; m.retune(next);
  m.throwFrom({320, 230}, {500, 100}, true); finish(m);
  check(m.position.x == 320 && m.position.y == 230,
        "release-speed threshold changes the same throw's interpretation");
  next.placement = Placement::AlwaysDock; m.retune(next);
  m.throwFrom({320, 230}, {}, true); finish(m);
  check(m.position.x == 12 && m.position.y == 12,
        "always-dock mode retains position-only docking for slow releases");
  next.placement = Placement::Free; m.retune(next);
  m.throwFrom({320, 230}, {1100, 600}, true); finish(m);
  check(m.position.x == 320 && m.position.y == 230,
        "free placement ignores throw velocity");
  m.throwFrom({320, -20}, {}, false); finish(m);
  check(m.position.x == 320 && m.position.y == 12,
        "free placement returns an out-of-bounds drop into the visible area");
  next.margin = 32; m.retune(next); finish(m);
  check(m.position.x == 320 && m.position.y == 32,
        "retuning the inset preserves free horizontal placement");
  m.throwFrom({-100, 230}, {}, true); finish(m);
  check(m.phase == Phase::Tucked,
        "explicit side tuck still works in free-placement mode");
  m.placeAt({320, 230});
  next = m.settings; next.response = .6; m.retune(next); finish(m);
  check(m.position.x == 320 && m.position.y == 230 && m.tucked == Side::None,
        "restored free placement survives live tuning without docking");

  m = Motion{};
  m.tuck(Side::Right); finish(m); m.restore(); m.step(.04);
  auto grab = m.position + Point{10, 90};
  m.begin(grab, 10); m.end(10.1); finish(m);
  check(m.position.x == 668 && m.position.y == 12 && m.decision == Decision::Restore,
        "click interruption resumes restore to a fully visible destination");
  next = m.settings; next.margin = 24; m.retune(next); finish(m);
  check(m.position.x == 656 && m.position.y == 24,
        "inset tuning after interrupted restore keeps the window fully visible");

  for (bool above : {false, true}) {
    m = Motion{}; m.settings.placement = Placement::Free;
    m.throwFrom({300, above ? 540.0 : -20.0}, {}, false); m.step(.02);
    before = m.position; grab = before + Point{40, 90};
    m.begin(grab, 20); m.drag(grab + Point{1, 0}, 20.01);
    check(near(m.position.x, before.x + 1) && near(m.position.y, before.y),
          above ? "upper-boundary re-grab does not reapply resistance" :
                  "lower-boundary re-grab does not reapply resistance");
    m.drag(grab + Point{1, above ? -1.0 : 1.0}, 20.02);
    check(near(m.position.y, before.y + (above ? -1 : 1)),
          above ? "upper-boundary inward pull follows the pointer" :
                  "lower-boundary inward pull follows the pointer");
    m.drag(grab + Point{1, above ? 1.0 : -1.0}, 20.03);
    const double outward = (m.position.y - before.y) * (above ? 1 : -1);
    check(outward > 0 && outward < 1,
          above ? "upper-boundary outward pull is resisted without jumping" :
                  "lower-boundary outward pull is resisted without jumping");
  }

  m = Motion{}; next = m.settings;
  next.free_speed = 800; next.projection = .9; m.retune(next);
  m.throwFrom({640, 30}, {-500, 0}, false);
  check(m.target.x == 668 && m.target.y == 12,
        "deliberate nearby attraction uses the nearby dock rather than a projected opposite dock");
  next.response = .6; m.retune(next);
  check(m.target.x == 668 && m.target.y == 12,
        "live retuning preserves the nearby deliberate attraction");
  m.throwFrom({640, 30}, {-800, 0}, false);
  check(m.target.x == 668 && m.target.y == 12,
        "release speed equal to the deliberate threshold attracts locally");
  m.throwFrom({640, 30}, {-800.01, 0}, false);
  check(m.target.x == 12 && m.target.y == 12,
        "release speed above the deliberate threshold projects the destination");
  m.throwFrom({620, 12}, {}, false);
  check(m.decision == Decision::Dock && m.target.x == 668,
        "slow drops exactly at the attraction radius still snap");
  m.throwFrom({619.99, 12}, {}, false);
  check(m.decision == Decision::Keep && m.target.x == 619.99,
        "slow drops beyond the attraction radius stay where placed");

  for (bool right : {false, true}) {
    m = Motion{}; m.settings.response = .9; m.settings.damping = .65;
    m.throwFrom({right ? 900.0 : -220.0, 200}, {right ? 1800.0 : -1800.0, 0}, true);
    bool accessible = true;
    for (int i = 0; i < 1200; ++i) {
      m.step(1.0 / 120);
      accessible &= m.position.x >= -320 + m.settings.handle &&
                    m.position.x <= 1000 - m.settings.handle;
    }
    check(accessible && m.phase == Phase::Tucked && length(m.velocity) == 0,
          right ? "right tuck keeps its handle exposed throughout underdamped overshoot" :
                  "left tuck keeps its handle exposed throughout underdamped overshoot");
  }

  m = Motion{}; next = m.settings; next.docking = Docking::SideEdges; m.retune(next);
  m.throwFrom({60, 210}, {10, 0}, false);
  check(m.decision == Decision::Dock && m.target.x == 12 && m.target.y == 210,
        "smart side-edge mode attracts a slow nearby drop at its existing height");
  m.throwFrom({60.01, 210}, {10, 0}, false);
  check(m.decision == Decision::Keep && m.target.x == 60.01 && m.target.y == 210,
        "smart side-edge mode keeps a slow drop outside the attraction distance");
  m.throwFrom({300, 210}, {1000, 100}, false);
  check(m.decision == Decision::Dock && m.target.x == 668 && near(m.target.y, 259.9),
        "smart side-edge mode projects a faster throw along the edge");

  m = Motion{};
  m.throwFrom({320, 230}, {500, 100}, false); finish(m);
  next = m.settings; next.free_speed = 600; m.retune(next); m.replay(); finish(m);
  check(m.decision == Decision::Keep && m.position.x == 320 && m.position.y == 230,
        "replay reclassifies the same throw with a changed release-speed threshold");
  next.placement = Placement::AlwaysDock; m.retune(next); m.replay(); finish(m);
  check(m.decision == Decision::Dock && m.position.x == 668 && m.position.y == 508,
        "replay applies always-dock mode to the same stored throw");
  next.placement = Placement::Free; m.retune(next); m.replay(); finish(m);
  check(m.decision == Decision::Keep && m.position.x == 320 && m.position.y == 230,
        "replay applies free mode to the same stored throw");

  m = Motion{}; m.settings.response = .9; m.settings.damping = .65;
  m.throwFrom({300, 500}, {0, 5000}, false);
  bool vertically_accessible = true;
  for (int i = 0; i < 1200; ++i) {
    m.step(1.0 / 120);
    vertically_accessible &= m.position.y >= -180 + m.settings.handle &&
                             m.position.y <= 700 - m.settings.handle;
  }
  check(vertically_accessible && m.phase == Phase::Resting,
        "vertical spring overshoot leaves a grabbable part onscreen");

  for (double width : {200.0, 320.0, 640.0}) {
    for (bool right : {false, true}) {
      m = Motion{}; m.size.width = width;
      double overlap = width * .25;
      auto drop = [&](double amount) {
        m.throwFrom({right ? 1000 - width + amount : -amount, 200}, {}, true);
      };
      drop(overlap - .01);
      check(m.tucked == Side::None,
            "below 25% stays untucked width=" + std::to_string(width) + (right ? " right" : " left"));
      drop(overlap); finish(m);
      check(m.phase == Phase::Tucked && m.tucked == (right ? Side::Right : Side::Left),
            "25% tucks at the same fraction width=" + std::to_string(width) + (right ? " right" : " left"));
    }
  }
  m = Motion{}; m.settings.stash_percent = 0;
  m.throwFrom({0, 200}, {}, true);
  check(m.tucked == Side::None, "zero-percent threshold still requires crossing the screen edge");
  m.throwFrom({-.01, 200}, {}, true);
  check(m.tucked == Side::Left, "zero-percent threshold tucks on any positive overlap");

  // Release previews: predict() must describe exactly what end() then does.
  m = Motion{};
  check(m.predict(0).decision == Decision::None, "no preview outside a drag");
  m.placeAt({320, 230});
  m.begin({400, 300}, 30);
  check(m.predict(30).decision == Decision::Keep, "a press without movement previews staying put");
  m.drag({720, 100}, 30.5);
  auto preview = m.predict(30.7);
  check(preview.decision == Decision::Dock && preview.target.x == 668 && preview.target.y == 12 &&
        preview.speed == 0, "a paused drag within snap distance previews the nearby corner");
  m.end(30.7);
  check(m.target.x == preview.target.x && m.target.y == preview.target.y,
        "the corner preview matches the release");
  m.placeAt({320, 230});
  m.begin({400, 300}, 31); m.drag({420, 300}, 31.5);
  check(m.predict(31.7).decision == Decision::Keep, "a paused interior drag previews staying put");
  m.begin({420, 300}, 32); m.drag({420 + 410 + 80, 300}, 32.5);
  preview = m.predict(32.7);
  check(preview.decision == Decision::Tuck && preview.side == Side::Right && preview.target.x == 972,
        "dragging past the tuck threshold previews a right tuck");
  m.end(32.7); finish(m);
  start = m.position;
  m.begin(start + Point{14, 80}, 33);
  preview = m.predict(33);
  check(preview.decision == Decision::Restore && !preview.moved,
        "pressing a tucked strip previews restore as an unmoved click");
  m.drag(start + Point{14 - 30, 80}, 33.1);
  check(m.predict(33.3).decision == Decision::Tuck, "an inward pull up to the restore distance previews tuck");
  m.drag(start + Point{14 - 31, 80}, 33.4);
  preview = m.predict(33.6);
  check(preview.decision == Decision::Restore && preview.target.x == 668 && preview.moved,
        "pulling past the restore distance previews the restore spot");

  std::mt19937 random(7);
  auto uniform = [&](double low, double high) {
    return std::uniform_real_distribution<double>(low, high)(random);
  };
  int previews[5] = {};
  for (int trial = 0; trial < 4000; ++trial) {
    m = Motion{};
    m.settings.placement = static_cast<Placement>(trial % 3);
    m.settings.docking = trial % 7 < 4 ? Docking::Corners : Docking::SideEdges;
    m.settings.free_speed = uniform(0, 800);
    m.settings.snap_distance = uniform(0, 180);
    m.settings.stash_percent = uniform(0, 75);
    m.settings.stash_velocity = uniform(300, 1800);
    m.settings.restore_distance = uniform(10, 80);
    const int start = trial % 4;
    if (start == 0) m.placeAt({uniform(0, 700), uniform(0, 520)});
    if (start == 1) { m.tuck(trial % 8 < 4 ? Side::Left : Side::Right); finish(m); }
    if (start == 2) { m.throwFrom({uniform(0, 680), uniform(0, 520)}, {uniform(-2000, 2000), uniform(-2000, 2000)}, true); m.step(uniform(0, .2)); }
    double time = 100 + trial;
    Point pointer = m.position + Point{uniform(1, 319), uniform(1, 179)};
    m.begin(pointer, time);
    const int moves = trial % 5 == 0 ? 0 : 1 + trial % 9;
    for (int i = 0; i < moves; ++i) {
      time += uniform(.004, .03);
      pointer = pointer + Point{uniform(-60, 60), uniform(-40, 40)} * (trial % 3 == 0 ? .1 : 1);
      m.drag(pointer, time);
    }
    const double release_time = time + std::array<double, 4>{0, .01, .05, .2}[trial % 4];
    const Outcome predicted = m.predict(release_time);
    Motion released = m;
    released.end(release_time);
    const Side tucked = predicted.decision == Decision::Tuck ? predicted.side : Side::None;
    const bool decision_matches = predicted.decision == released.decision ||
        (predicted.decision == Decision::Dock && start == 2);
    if (!(released.target.x == predicted.target.x && released.target.y == predicted.target.y &&
          released.tucked == tucked && decision_matches)) {
      std::cerr << "trial " << trial << " predicted " << static_cast<int>(predicted.decision)
                << " got " << static_cast<int>(released.decision) << '\n';
      check(false, "randomized release preview matches release");
    }
    ++previews[static_cast<int>(predicted.decision)];
  }
  check(previews[1] && previews[2] && previews[3] && previews[4],
        "randomized release previews matched for keep, dock, tuck and restore");
  // Release momentum away from the destination is dropped instead of overshooting backward.
  m = Motion{}; m.settings.placement = Placement::AlwaysDock; m.settings.projection = 0;
  m.throwFrom({600, 400}, {-1200, 0}, false);
  check(m.target.x == 668 && m.target.y == 508 && m.velocity.x == 0 && m.velocity.y == 0,
        "a throw away from its dock keeps no momentum heading away");
  double farthest = 600;
  for (int i = 0; i < 1200; ++i) { m.step(1.0 / 120); farthest = std::min(farthest, m.position.x); }
  check(farthest >= 600 - 1e-9 && m.position.x == 668,
        "a settle never shoots in the drag direction before returning");
  m.settings.projection = Settings{}.projection;
  m.throwFrom({300, 100}, {900, 900}, false);
  check(m.velocity.x > 0 && m.velocity.y > 0,
        "momentum toward the dock is preserved");
  // A gentle preview ignores mid-drag momentum but still reports the measured speed.
  m = Motion{}; m.settings.docking = Docking::SideEdges;
  m.placeAt({340, 260});
  m.begin({400, 300}, 50); m.drag({400, 340}, 50.02); m.drag({400, 380}, 50.04);
  const Outcome thrown = m.predict(50.04), gentle = m.predict(50.04, true);
  check(thrown.decision == Decision::Dock && gentle.decision == Decision::Keep &&
        near(gentle.speed, thrown.speed) && gentle.speed > 1000,
        "a fast vertical drag previews a gentle stay instead of a projected edge corner");
  std::cout << checks << " checks passed\n";
}
