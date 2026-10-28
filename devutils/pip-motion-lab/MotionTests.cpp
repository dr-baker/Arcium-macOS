#include "Motion.hpp"
#include <cstdlib>
#include <iostream>
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
  std::cout << checks << " checks passed\n";
}
