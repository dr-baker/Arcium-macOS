#include "Gestures.hpp"
#include <cstdlib>
#include <iostream>

using namespace pip_motion;
static int checks = 0;
static void check(bool value, const char* name) {
  ++checks;
  if (!value) { std::cerr << "FAIL: " << name << '\n'; std::exit(1); }
}
static bool near(double a, double b) { return std::abs(a - b) < .0001; }

int main() {
  Motion motion({0, 0, 1400, 1000});
  motion.settings = selectedSettings();
  motion.placeAt({400, 350});
  Gestures input(motion);
  input.beginPan(1);
  input.pan({40, 25}, 1.01);
  check(near(motion.position.x, 440) && near(motion.position.y, 375), "diagonal fingers move both axes");
  input.pan({-12, 30}, 1.02);
  check(near(motion.position.x, 428) && near(motion.position.y, 405), "direction changes have no axis latch");
  input.endPan(2);
  check(motion.decision == Decision::Keep, "held careful drop stays put");
  check(input.kind() == Gestures::Kind::None, "pan ends cleanly");
  const Point paused = motion.position;
  input.pan({100, 100}, 2.1);
  check(near(motion.position.x, paused.x) && near(motion.position.y, paused.y), "late deltas do not move a released card");

  motion.placeAt({400, 350});
  input.beginPinch();
  input.magnify(.5);
  check(near(motion.size.width, 480) && near(motion.size.height, 270), "pinch preserves video aspect");
  check(near(motion.position.x + motion.size.width / 2, 560) &&
        near(motion.position.y + motion.size.height / 2, 440), "pinch holds card center steady");
  input.magnify(-.2);
  check(near(motion.size.width, 384), "pinch deltas accumulate during gesture");
  input.endPinch(true);
  check(near(motion.size.width, 320) && near(motion.position.x, 400) &&
        near(motion.position.y, 350), "cancelled pinch restores starting size and position");

  input.beginPinch();
  input.magnify(100);
  const Rect area = motion.area();
  check(motion.position.x >= area.x && motion.position.y >= area.y &&
        motion.position.x + motion.size.width <= area.x + area.width &&
        motion.position.y + motion.size.height <= area.y + area.height, "large pinch fits the work area");
  input.magnify(-100);
  check(near(motion.size.width, 240), "small pinch stops at usable minimum");
  const double finiteWidth = motion.size.width;
  input.magnify(NAN);
  check(motion.size.width == finiteWidth, "invalid device magnification cannot corrupt size");
  input.endPinch();
  check(input.kind() == Gestures::Kind::None && near(motion.size.width, 240), "pinch end retains selected size");

  motion.environment(area, {320, 180}); motion.placeAt({400, 350});

  input.beginPan(3); input.pan({25, 35}, 3.01);
  input.beginPinch(); input.magnify(.25);
  const Point pinched = motion.position;
  input.pan({400, 400}, 3.02); input.endPan(3.03);
  check(input.kind() == Gestures::Kind::Pinch && near(motion.position.x, pinched.x),
        "pan events cannot move a pinching card");
  input.endPinch();

  motion.tuck(Side::Right);
  const double tuckedWidth = motion.size.width;
  input.beginPinch(); input.magnify(.5);
  check(near(motion.size.width, tuckedWidth) && motion.tucked == Side::Right,
        "tucked restore strip does not resize");

  Motion small({0, 0, 200, 120}); Gestures smallInput(small);
  smallInput.beginPinch(); smallInput.magnify(1); smallInput.endPinch();
  check(small.size.width <= 200 && small.size.height <= 120, "small displays take precedence over minimum size");

  Motion seam({0, 0, 1000, 800});
  seam.settings = selectedSettings();
  seam.environment(seam.area(), {320, 180}, {false, true, true, true}, Rect{-40, 0, 1080, 850});
  seam.placeAt({100, 300});
  Gestures seamInput(seam);
  seamInput.beginPinch(); seamInput.magnify(0); seamInput.endPinch();
  seamInput.beginPan(5); seamInput.pan({-250, 20}, 5.01);
  check(near(seam.position.x, -150) && near(seam.position.y, 320), "zero-delta pinch keeps open display seams traversable");
  seamInput.endPan(5.02, true);
  check(near(seam.physicalArea().x, -40) && near(seam.physicalArea().height, 850), "pinch preserves physical presentation boundaries");

  seam.placeAt({100, 300});
  seamInput.beginPinch(); seamInput.magnify(.5);
  seam.environment({-800, 0, 1800, 1100}, seam.size, {true, false, true, true}, Rect{-850, 0, 1900, 1150});
  seamInput.endPinch(true);
  check(near(seam.area().width, 1800) && !seam.exteriorEdges().right && near(seam.physicalArea().x, -850),
        "cancelled pinch keeps a changed display's complete environment");

  Motion fitted({0, 0, 1000, 800}); fitted.settings.margin = 12;
  Gestures fitInput(fitted); fitInput.beginPinch(); fitInput.magnify(100); fitInput.endPinch();
  Settings next = fitted.settings; next.margin = 36; fitted.retune(next);
  fitted.placeAt(fitted.position);
  check(fitted.size.width <= 928 && fitted.position.x >= 36 &&
        fitted.position.x + fitted.size.width <= 964, "increasing inset after a maximum pinch keeps valid fitting bounds");
  fitInput.beginPinch();
  next.margin = 80; fitted.retune(next); fitInput.endPinch(true);
  check(fitted.settings.margin == 80 && fitted.size.width <= 840 &&
        fitted.position.x >= 80 && fitted.position.x + fitted.size.width <= 920,
        "pinch cancellation retains live inset tuning and refits the restored size");

  Motion reset({0, 0, 1000, 400}); reset.settings.margin = 0;
  Gestures resetInput(reset); resetInput.beginPinch(); resetInput.magnify(100); resetInput.endPinch();
  reset.resetSettings(selectedSettings()); reset.tuck(Side::Right);
  check(reset.size.height <= 400 - 2 * reset.settings.margin &&
        reset.target.y >= reset.settings.margin && std::isfinite(reset.target.y),
        "reset everything after maximum pinch leaves valid tuck bounds");
  reset.restore();
  check(reset.target.y >= reset.settings.margin &&
        reset.target.y + reset.size.height <= 400 - reset.settings.margin,
        "restore after maximum pinch and reset stays inside the inset");
  reset.environment({0, 0, 400, 240}, reset.size);
  reset.tuck(Side::Right);
  check(reset.size.width <= 400 - 2 * reset.settings.margin &&
        reset.size.height <= 240 - 2 * reset.settings.margin && std::isfinite(reset.target.y),
        "moving a resized card to a smaller display refits before tucking");
  std::cout << "PASS: " << checks << " gesture checks\n";
}
