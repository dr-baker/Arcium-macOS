#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <optional>

namespace pip_motion {

struct Point {
  double x = 0, y = 0;
  Point operator+(Point p) const { return {x + p.x, y + p.y}; }
  Point operator-(Point p) const { return {x - p.x, y - p.y}; }
  Point operator*(double n) const { return {x * n, y * n}; }
};
inline double length(Point p) { return std::hypot(p.x, p.y); }
// Keeps only the part of a release velocity that heads toward the destination, so a
// settle never shoots away in the drag direction before turning back.
inline Point toward(Point velocity, Point from, Point to) {
  const Point direction = to - from;
  const double distance = length(direction);
  if (distance < 1e-6) return {};
  const Point unit = direction * (1 / distance);
  const double speed = velocity.x * unit.x + velocity.y * unit.y;
  return speed > 0 ? unit * speed : Point{};
}
struct Size { double width = 320, height = 180; };
struct Rect { double x = 0, y = 0, width = 1000, height = 700; };
enum class Docking { Corners, SideEdges, AllEdges };
enum class Placement { Smart, AlwaysDock, Free };
enum class Side { None, Left, Right };
enum class Phase { Resting, Dragging, Settling, Tucked };
enum class Decision { None, Keep, Dock, Tuck, Restore };

// What a release would do: the decision, tucked side, and resting destination.
struct Outcome {
  Decision decision = Decision::None;
  Side side = Side::None;
  Point target;
  double speed = 0;
  bool moved = false;  // The drag has displaced the window, so this is not a click.
};

struct Settings {
  double response = 0.40;
  double damping = 1.00;
  double projection = 0.499;
  double margin = 12;
  double stash_percent = 25;
  double stash_velocity = 900;
  double restore_distance = 30;
  double handle = 28;
  double resistance = 0.35;
  double free_speed = 140;
  double snap_distance = 48;
  // Press into any edge: how far the window must be pushed in to dock, and to tuck at a side,
  // as resisted displacement divided by the window's size on that axis.
  double press_dock = 2;
  double press_tuck = 12;
  Docking docking = Docking::Corners;
  Placement placement = Placement::Smart;
};

inline Settings selectedSettings() {
  Settings s;
  s.response = .625; s.damping = .759; s.projection = .266; s.margin = 21.93;
  s.stash_percent = 30; s.stash_velocity = 1009; s.restore_distance = 29.86;
  s.handle = 26.35; s.resistance = .631; s.free_speed = 800; s.snap_distance = 64;
  s.press_dock = 2.4; s.press_tuck = 24.7;
  s.docking = Docking::AllEdges; s.placement = Placement::Smart;
  return s;
}
struct FeedbackSettings {
  bool enabled = true, haptics = true;
  double lift = .75, pickupShadow = -.44, shadowBox = .20, shadowIntensity = 1.10;
  double settle = .62, settleDelay = .08, settleEase = .28;
  double press = .40, glow = 0, edge = .80, lean = 40, dockShadow = .90;
};
struct Edges {
  bool left = true, right = true, bottom = true, top = true;
};

enum class SpringPreset { Baseline, Snappy, Soft, PositionOnly };
inline Settings springPreset(Settings current, SpringPreset preset) {
  if (preset == SpringPreset::PositionOnly) {
    current.projection = 0;
    return current;
  }
  const Settings defaults;
  current.response = defaults.response;
  current.damping = defaults.damping;
  current.projection = defaults.projection;
  if (preset == SpringPreset::Snappy) { current.response = .28; current.projection = .35; }
  if (preset == SpringPreset::Soft) { current.response = .60; current.damping = .85; }
  return current;
}

inline double dockCueDistance(const Settings& settings) {
  return settings.docking != Docking::AllEdges && settings.placement == Placement::Smart ?
      std::max(settings.snap_distance, 48.0) : 48.0;
}

inline double rubber(double distance, double extent, double coefficient) {
  const double magnitude = std::abs(distance);
  return std::copysign((1 - 1 / (1 + coefficient * magnitude / extent)) * extent,
                       distance);
}

inline double rubberInput(double distance, double extent, double coefficient) {
  const double magnitude = std::min(std::abs(distance), extent - 1e-6);
  return std::copysign(magnitude * extent / (coefficient * (extent - magnitude)), distance);
}

// Exact damped-oscillator evolution makes settlement independent of timer cadence.
inline void spring(double& position, double& velocity, double target,
                   double response, double damping, double dt) {
  const double omega = 2 * std::acos(-1.0) / response;
  const double offset = position - target;
  if (std::abs(damping - 1) < 1e-5) {
    const double a = velocity + omega * offset;
    const double decay = std::exp(-omega * dt);
    position = target + (offset + a * dt) * decay;
    velocity = (velocity - omega * a * dt) * decay;
  } else if (damping < 1) {
    const double wd = omega * std::sqrt(1 - damping * damping);
    const double a = offset;
    const double b = (velocity + damping * omega * offset) / wd;
    const double decay = std::exp(-damping * omega * dt);
    const double c = std::cos(wd * dt), s = std::sin(wd * dt);
    position = target + decay * (a * c + b * s);
    velocity = decay * ((b * wd - damping * omega * a) * c +
                        (-a * wd - damping * omega * b) * s);
  } else {
    const double q = std::sqrt(damping * damping - 1);
    const double r1 = -omega * (damping - q), r2 = -omega * (damping + q);
    const double a = (velocity - r2 * offset) / (r1 - r2), b = offset - a;
    const double e1 = std::exp(r1 * dt), e2 = std::exp(r2 * dt);
    position = target + a * e1 + b * e2;
    velocity = a * r1 * e1 + b * r2 * e2;
  }
}

class VelocityTracker {
 public:
  void reset() { samples_.clear(); }
  void add(Point point, double time) {
    if (!samples_.empty() && time <= samples_.back().time) return;
    samples_.push_back({point, time});
    while (samples_.size() > 2 && time - samples_.front().time > 0.10)
      samples_.pop_front();
  }
  Point value(double now) const {
    if (samples_.size() < 2 || now - samples_.back().time > 0.08) return {};
    const double span = samples_.back().time - samples_.front().time;
    if (span < 0.004) return {};
    Point velocity = (samples_.back().point - samples_.front().point) * (1 / span);
    const double speed = length(velocity);
    return speed > 5000 ? velocity * (5000 / speed) : velocity;
  }
 private:
  struct Sample { Point point; double time; };
  std::deque<Sample> samples_;
};

class Motion {
 public:
  explicit Motion(Rect area = {}) : area_(area), presentation_area_(area) { reset(); }
  Settings settings;
  Size size;
  Point position, velocity, target;
  Phase phase = Phase::Resting;
  Side tucked = Side::None;
  Decision decision = Decision::None;
  double release_speed = 0, dock_distance = 0;
  // Presented displacement past this drag's resistance bounds, after presentation clamping.
  Point pressed;
  // Re-grabbing outside an inset starts a fresh press at the grabbed presentation.
  Point pressDepth(Point press) const {
    return {100 * press.x / size.width, 100 * press.y / size.height};
  }
  Point depth() const { return pressDepth(pressed); }

  Point dockTarget(Point origin, Point release_velocity) const {
    const Point projected = origin + release_velocity * settings.projection;
    const auto points = corners();
    if (settings.docking == Docking::AllEdges) {
      Point p{std::clamp(projected.x, points[0].x, points[1].x),
              std::clamp(projected.y, points[0].y, points[2].y)};
      const double left = p.x - points[0].x, right = points[1].x - p.x;
      const double bottom = p.y - points[0].y, top = points[2].y - p.y;
      double nearest = INFINITY;
      Point target = p;
      if (edges_.left && left < nearest) { nearest = left; target = {points[0].x, p.y}; }
      if (edges_.right && right < nearest) { nearest = right; target = {points[1].x, p.y}; }
      if (edges_.bottom && bottom < nearest) { nearest = bottom; target = {p.x, points[0].y}; }
      if (edges_.top && top < nearest) target = {p.x, points[2].y};
      p = target;
      return p;
    }
    if (settings.docking == Docking::SideEdges) {
      return {projected.x < (points[0].x + points[1].x) / 2 ? points[0].x : points[1].x,
              std::clamp(projected.y, points[0].y, points[2].y)};
    }
    return *std::min_element(points.begin(), points.end(), [&](Point a, Point b) {
      return length(a - projected) < length(b - projected);
    });
  }

  void reset() {
    tucked = Side::None;
    position = target = corners()[1];
    velocity = {};
    pressed = {};
    phase = Phase::Resting;
    goal_ = Goal::Dock;
    restore_point_ = position;
    restore_side_ = Side::Right;
    last_throw_.reset();
    decision = Decision::None;
  }

  void begin(Point pointer, double time) {
    start_settling_ = phase == Phase::Settling;
    start_position_ = position;
    resistance_anchor_ = position;
    last_pointer_ = pointer;
    offset_ = pointer - position;
    drag_side_ = tucked;
    pressed = {};
    phase = Phase::Dragging;
    velocity = {};
    tracker_.reset();
    tracker_.add(pointer, time);
  }

  void placeAt(Point origin) {
    tucked = Side::None;
    position = target = clampVisible(origin);
    velocity = {};
    pressed = {};
    phase = Phase::Resting;
    goal_ = Goal::Free;
    decision = Decision::None;
    last_throw_.reset();
  }

  void resetSettings(const Settings& defaults = {}) {
    if (phase == Phase::Resting) {
      settings = defaults;
      settle(clampVisible(position), {}, Goal::Free);
    } else {
      retune(defaults);
    }
  }

  void drag(Point pointer, double time) {
    if (phase != Phase::Dragging) return;
    last_pointer_ = pointer;
    Point next = pointer - offset_;
    // An interrupted spring may already be beyond a boundary. Anchor resistance
    // at that presentation position so re-grabbing does not resist it twice.
    const Rect limits = dragLimits();
    const double low = limits.y, high = limits.y + limits.height;
    if (edges_.bottom && next.y < low) next.y = low + rubber(next.y - low, size.height, settings.resistance);
    if (edges_.top && next.y > high) next.y = high + rubber(next.y - high, size.height, settings.resistance);
    // Press mode resists the sides too, so a little push docks and a long push tucks.
    if (settings.docking == Docking::AllEdges && drag_side_ == Side::None) {
      const double left = limits.x, right = limits.x + limits.width;
      if (edges_.left && next.x < left) next.x = left + rubber(next.x - left, size.width, settings.resistance);
      if (edges_.right && next.x > right) next.x = right + rubber(next.x - right, size.width, settings.resistance);
    }
    position = next;
    constrainPresentation();
    updatePressed();
    tracker_.add(pointer, time);
  }

  void end(double time) {
    if (phase != Phase::Dragging) return;
    Point release = tracker_.value(time);
    if (drag_side_ != Side::None) {
      velocity = release;
      if (restoresOnRelease(release)) restore();
      else tuck(drag_side_);
      return;
    }
    if (unmovedGrab(release)) {
      settleUnmovedGrab();
      return;
    }
    throwFrom(position, release, true, pressed);
  }

  // Side-effect-free preview of end(time), using the same classification. A gentle preview
  // classifies as if released without momentum, while still reporting the current speed.
  Outcome predict(double time, bool gentle = false) const {
    if (phase != Phase::Dragging) return {};
    const Point measured = tracker_.value(time);
    const Point release = gentle ? Point{} : measured;
    Outcome outcome;
    if (drag_side_ != Side::None) {
      outcome = restoresOnRelease(release) ?
          Outcome{Decision::Restore, restore_side_, restoreTarget(), length(release)} :
          Outcome{Decision::Tuck, drag_side_, tuckTarget(drag_side_, position.y), length(release)};
    } else {
      outcome = unmovedGrab(release) ? unmovedOutcome() : classify(position, release, true, pressed);
    }
    outcome.moved = length(position - start_position_) >= 2;
    outcome.speed = length(measured);
    return outcome;
  }

  Outcome classify(Point origin, Point release, bool allow_stash, Point press = {}) const {
    const double speed = length(release);
    if (settings.docking == Docking::AllEdges) {
      const Point in = pressDepth(press);
      const bool side = std::abs(in.x) > 0 && std::abs(in.x) >= settings.press_dock;
      const bool end = std::abs(in.y) > 0 && std::abs(in.y) >= settings.press_dock;
      if (allow_stash && std::abs(in.x) > 0 && std::abs(in.x) >= settings.press_tuck) {
        const Side tuck_side = press.x < 0 ? Side::Left : Side::Right;
        return {Decision::Tuck, tuck_side, tuckTarget(tuck_side, origin.y), speed};
      }
      if (side || end) {
        const auto points = corners();
        Point target = clampVisible(origin);
        if (side) target.x = press.x < 0 ? points[0].x : points[1].x;
        if (end) target.y = press.y < 0 ? points[0].y : points[2].y;
        return {Decision::Dock, Side::None, target, speed};
      }
    }
    const double left_overlap = area_.x - origin.x;
    const double right_overlap = origin.x + size.width - area_.x - area_.width;
    const bool horizontal = std::abs(release.x) > 1.6 * std::abs(release.y);
    const bool fling_left = origin.x < area_.x + 32 &&
        release.x < -settings.stash_velocity && horizontal;
    const bool fling_right = origin.x + size.width > area_.x + area_.width - 32 &&
        release.x > settings.stash_velocity && horizontal;
    const double tuck_distance = size.width * settings.stash_percent / 100;
    if (settings.docking != Docking::AllEdges && allow_stash &&
        ((left_overlap > 0 && left_overlap >= tuck_distance) || fling_left))
      return {Decision::Tuck, Side::Left, tuckTarget(Side::Left, origin.y), speed};
    if (settings.docking != Docking::AllEdges && allow_stash &&
        ((right_overlap > 0 && right_overlap >= tuck_distance) || fling_right))
      return {Decision::Tuck, Side::Right, tuckTarget(Side::Right, origin.y), speed};
    const bool deliberate = speed <= settings.free_speed;
    // Press mode docks only by pressing; nearness alone never snaps a slow drop.
    const bool near_dock = settings.docking != Docking::AllEdges &&
        length(origin - dockTarget(origin, {})) <= settings.snap_distance;
    if (settings.placement == Placement::Free ||
        (settings.placement == Placement::Smart && deliberate && !near_dock))
      return {Decision::Keep, Side::None, clampVisible(origin), speed};
    return {Decision::Dock, Side::None, dockDestination(origin, release), speed};
  }

  void cancel() {
    if (phase != Phase::Dragging) return;
    velocity = {};
    if (drag_side_ != Side::None) tuck(drag_side_);
    else settleUnmovedGrab();
  }

  void throwFrom(Point origin, Point release, bool allow_stash, Point press = {}) {
    position = origin;
    velocity = release;
    last_throw_ = Throw{origin, release, allow_stash, press};
    release_speed = length(release);
    dock_distance = length(origin - dockTarget(origin, {}));
    tucked = Side::None;
    const Outcome outcome = classify(origin, release, allow_stash, press);
    if (outcome.decision == Decision::Tuck) {
      tuck(outcome.side);
    } else {
      decision = outcome.decision;
      const bool dock = outcome.decision == Decision::Dock;
      settle(outcome.target, dock ? toward(release, origin, outcome.target) : Point{},
             dock ? Goal::Dock : Goal::Free);
    }
  }

  void tuck(Side side) {
    decision = Decision::Tuck;
    if (side == Side::None)
      side = position.x + size.width / 2 < area_.x + area_.width / 2 ? Side::Left : Side::Right;
    const Point destination = tuckTarget(side, position.y);
    if (tucked == Side::None) {
      exact_restore_ = false;
      restore_point_ = {side == Side::Left ? area_.x + settings.margin :
          area_.x + area_.width - size.width - settings.margin, destination.y};
    }
    restore_side_ = side;
    tucked = side;
    settle(destination, toward(velocity, position, destination), Goal::Stash);
  }

  void restore() {
    decision = Decision::Restore;
    tucked = Side::None;
    restore_point_ = restoreTarget();
    settle(restore_point_, toward(velocity, position, restore_point_), Goal::Restore);
  }

  void replay() {
    if (!last_throw_) return;
    const auto sample = *last_throw_;
    throwFrom(sample.origin, sample.velocity, sample.allow_stash, sample.press);
  }
  bool canReplay() const { return last_throw_.has_value(); }

  void retune(Settings next) {
    const bool changedBounds = next.margin != settings.margin || next.docking != settings.docking;
    settings = next;
    if (phase == Phase::Dragging) {
      if (changedBounds) resistance_anchor_ = position;
      const Rect limits = dragLimits();
      Point raw = position;
      if (edges_.bottom && raw.y < limits.y)
        raw.y = limits.y + rubberInput(raw.y - limits.y, size.height, settings.resistance);
      if (edges_.top && raw.y > limits.y + limits.height)
        raw.y = limits.y + limits.height + rubberInput(raw.y - limits.y - limits.height, size.height, settings.resistance);
      if (settings.docking == Docking::AllEdges && drag_side_ == Side::None) {
        if (edges_.left && raw.x < limits.x)
          raw.x = limits.x + rubberInput(raw.x - limits.x, size.width, settings.resistance);
        if (edges_.right && raw.x > limits.x + limits.width)
          raw.x = limits.x + limits.width + rubberInput(raw.x - limits.x - limits.width, size.width, settings.resistance);
      }
      offset_ = last_pointer_ - raw;
      updatePressed();
      return;
    }
    if (tucked != Side::None) {
      tuck(tucked);
    } else if (goal_ == Goal::Restore) {
      restore_point_ = restoreTarget();
      settle(restore_point_, velocity, Goal::Restore);
    } else if (goal_ == Goal::Free) {
      settle(clampVisible(target), velocity, Goal::Free);
    } else {
      Point next_target = dockTarget(position, {});
      if (phase == Phase::Settling && last_throw_) {
        const Outcome thrown = classify(last_throw_->origin, last_throw_->velocity,
                                        last_throw_->allow_stash, last_throw_->press);
        next_target = settings.docking == Docking::AllEdges && thrown.decision == Decision::Dock ?
            thrown.target : dockDestination(last_throw_->origin, last_throw_->velocity);
      }
      settle(next_target, velocity, Goal::Dock);
    }
  }

  bool step(double dt) {
    if (phase != Phase::Settling || dt <= 0 || !std::isfinite(dt)) return false;
    spring(position.x, velocity.x, target.x, settings.response, settings.damping, dt);
    spring(position.y, velocity.y, target.y, settings.response, settings.damping, dt);
    constrainPresentation();
    if (length(position - target) < 0.1 && length(velocity) < 1) {
      position = target;
      velocity = {};
      phase = tucked == Side::None ? Phase::Resting : Phase::Tucked;
    }
    return true;
  }

  Point centerOrigin() const {
    return {area_.x + (area_.width - size.width) / 2,
            area_.y + (area_.height - size.height) / 2};
  }
  // Switching displays changes the active work area without changing global pointer offset.
  void environment(Rect area, Size dimensions, Edges edges = {}, std::optional<Rect> physical = std::nullopt) {
    area_ = area;
    presentation_area_ = physical.value_or(area);
    size = dimensions;
    edges_ = edges;
    if (phase == Phase::Dragging) updatePressed();
  }
  void seed(Point origin, Side side = Side::None, Point restore = {}) {
    position = target = origin;
    tucked = side;
    phase = side == Side::None ? Phase::Resting : Phase::Tucked;
    goal_ = side == Side::None ? Goal::Free : Goal::Stash;
    restore_point_ = restore;
    exact_restore_ = side != Side::None;
    restore_side_ = side;
    velocity = pressed = {};
  }
  Point restorePosition() const { return restoreTarget(); }
  Point rawPosition(Point pointer) const { return pointer - offset_; }
  Rect area() const { return area_; }

 private:
  enum class Goal { Dock, Stash, Restore, Free };
  Rect dragLimits() const {
    const double left = std::min(area_.x + settings.margin, resistance_anchor_.x);
    const double right = std::max(area_.x + area_.width - size.width - settings.margin, resistance_anchor_.x);
    const double bottom = std::min(area_.y + settings.margin, resistance_anchor_.y);
    const double top = std::max(area_.y + area_.height - size.height - settings.margin, resistance_anchor_.y);
    return {left, bottom, right - left, top - bottom};
  }
  void updatePressed() {
    const Rect limits = dragLimits();
    pressed = {};
    if (edges_.bottom && position.y < limits.y) pressed.y = position.y - limits.y;
    if (edges_.top && position.y > limits.y + limits.height) pressed.y = position.y - limits.y - limits.height;
    if (settings.docking == Docking::AllEdges && drag_side_ == Side::None) {
      if (edges_.left && position.x < limits.x) pressed.x = position.x - limits.x;
      if (edges_.right && position.x > limits.x + limits.width) pressed.x = position.x - limits.x - limits.width;
    }
  }
  Point dockDestination(Point origin, Point release) const {
    const bool deliberate_attraction = settings.placement == Placement::Smart &&
        length(release) <= settings.free_speed;
    return dockTarget(origin, deliberate_attraction ? Point{} : release);
  }
  bool unmovedGrab(Point release) const {
    return length(position - start_position_) < 2 && length(release) < 1;
  }
  bool restoresOnRelease(Point release) const {
    const Point displacement = position - start_position_;
    const double inward = drag_side_ == Side::Left ? displacement.x : -displacement.x;
    const double inward_speed = drag_side_ == Side::Left ? release.x : -release.x;
    return length(displacement) < 2 || inward > settings.restore_distance ||
        inward_speed > settings.stash_velocity;
  }
  Point tuckTarget(Side side, double y) const {
    return {side == Side::Left ? area_.x - size.width + settings.handle :
                area_.x + area_.width - settings.handle,
            std::clamp(y, area_.y + settings.margin,
                area_.y + area_.height - size.height - settings.margin)};
  }
  Point restoreTarget() const {
    if (exact_restore_) return clampVisible(restore_point_);
    return {restore_side_ == Side::Left ? area_.x + settings.margin :
                area_.x + area_.width - size.width - settings.margin,
            std::clamp(restore_point_.y, area_.y + settings.margin,
                area_.y + area_.height - size.height - settings.margin)};
  }
  Outcome unmovedOutcome() const {
    if (start_settling_ && goal_ == Goal::Restore)
      return {Decision::Restore, restore_side_, restoreTarget(), 0};
    if (start_settling_ && goal_ == Goal::Dock)
      return {Decision::Dock, Side::None, dockTarget(target, {}), 0};
    return {Decision::Keep, Side::None, clampVisible(start_settling_ ? target : start_position_), 0};
  }
  void settleUnmovedGrab() {
    velocity = {};
    const Outcome outcome = unmovedOutcome();
    if (outcome.decision == Decision::Restore) {
      restore();
    } else if (outcome.decision == Decision::Dock) {
      settle(outcome.target, {}, Goal::Dock);
    } else {
      decision = Decision::Keep;
      release_speed = 0;
      dock_distance = length(outcome.target - dockTarget(outcome.target, {}));
      settle(outcome.target, {}, Goal::Free);
    }
  }
  void constrainPresentation() {
    auto bound = [](double& coordinate, double& speed, double low, double high) {
      if (coordinate < low) { coordinate = low; speed = std::max(0.0, speed); }
      if (coordinate > high) { coordinate = high; speed = std::min(0.0, speed); }
    };
    bound(position.x, velocity.x, edges_.left ? presentation_area_.x - size.width + settings.handle : -INFINITY,
          edges_.right ? presentation_area_.x + presentation_area_.width - settings.handle : INFINITY);
    bound(position.y, velocity.y, edges_.bottom ? presentation_area_.y - size.height + settings.handle : -INFINITY,
          edges_.top ? presentation_area_.y + presentation_area_.height - settings.handle : INFINITY);
  }
  Point clampVisible(Point p) const {
    return {std::clamp(p.x, area_.x + settings.margin,
                      area_.x + area_.width - size.width - settings.margin),
            std::clamp(p.y, area_.y + settings.margin,
                      area_.y + area_.height - size.height - settings.margin)};
  }
  std::array<Point, 4> corners() const {
    const double l = area_.x + settings.margin;
    const double r = area_.x + area_.width - size.width - settings.margin;
    const double b = area_.y + settings.margin;
    const double t = area_.y + area_.height - size.height - settings.margin;
    return {Point{l, b}, Point{r, b}, Point{l, t}, Point{r, t}};
  }
  void settle(Point destination, Point initial_velocity, Goal goal) {
    target = destination;
    velocity = initial_velocity;
    phase = Phase::Settling;
    goal_ = goal;
  }
  struct Throw { Point origin, velocity; bool allow_stash; Point press; };
  Rect area_;
  Rect presentation_area_;
  Edges edges_;
  Point offset_, start_position_, restore_point_, resistance_anchor_, last_pointer_;
  Side drag_side_ = Side::None;
  Side restore_side_ = Side::Right;
  bool start_settling_ = false;
  bool exact_restore_ = false;
  Goal goal_ = Goal::Dock;
  VelocityTracker tracker_;
  std::optional<Throw> last_throw_;
};

}  // namespace pip_motion
