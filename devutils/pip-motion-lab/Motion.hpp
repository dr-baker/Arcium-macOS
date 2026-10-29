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
struct Size { double width = 320, height = 180; };
struct Rect { double x = 0, y = 0, width = 1000, height = 700; };
enum class Docking { Corners, SideEdges };
enum class Placement { Smart, AlwaysDock, Free };
enum class Side { None, Left, Right };
enum class Phase { Resting, Dragging, Settling, Tucked };
enum class Decision { None, Keep, Dock, Tuck, Restore };

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
  Docking docking = Docking::Corners;
  Placement placement = Placement::Smart;
};

inline double rubber(double distance, double extent, double coefficient) {
  const double magnitude = std::abs(distance);
  return std::copysign((1 - 1 / (1 + coefficient * magnitude / extent)) * extent,
                       distance);
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
  explicit Motion(Rect area = {}) : area_(area) { reset(); }
  Settings settings;
  Size size;
  Point position, velocity, target;
  Phase phase = Phase::Resting;
  Side tucked = Side::None;
  Decision decision = Decision::None;
  double release_speed = 0, dock_distance = 0;

  Point dockTarget(Point origin, Point release_velocity) const {
    const Point projected = origin + release_velocity * settings.projection;
    const auto points = corners();
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
    offset_ = pointer - position;
    drag_side_ = tucked;
    phase = Phase::Dragging;
    velocity = {};
    tracker_.reset();
    tracker_.add(pointer, time);
  }

  void placeAt(Point origin) {
    tucked = Side::None;
    position = target = clampVisible(origin);
    velocity = {};
    phase = Phase::Resting;
    goal_ = Goal::Free;
    decision = Decision::None;
    last_throw_.reset();
  }

  void resetSettings() {
    if (phase == Phase::Resting) {
      settings = Settings{};
      settle(clampVisible(position), {}, Goal::Free);
    } else {
      retune(Settings{});
    }
  }

  void drag(Point pointer, double time) {
    if (phase != Phase::Dragging) return;
    Point next = pointer - offset_;
    // An interrupted spring may already be beyond a boundary. Anchor resistance
    // at that presentation position so re-grabbing does not resist it twice.
    const double low = std::min(area_.y + settings.margin, start_position_.y);
    const double high = std::max(area_.y + area_.height - size.height - settings.margin,
                                 start_position_.y);
    if (next.y < low)
      next.y = low + rubber(next.y - low, size.height, settings.resistance);
    if (next.y > high)
      next.y = high + rubber(next.y - high, size.height, settings.resistance);
    position = next;
    constrainPresentation();
    tracker_.add(pointer, time);
  }

  void end(double time) {
    if (phase != Phase::Dragging) return;
    Point release = tracker_.value(time);
    const Point displacement = position - start_position_;
    if (drag_side_ != Side::None) {
      const double inward = drag_side_ == Side::Left ? displacement.x : -displacement.x;
      const double inward_speed = drag_side_ == Side::Left ? release.x : -release.x;
      if (length(displacement) < 2 || inward > settings.restore_distance ||
          inward_speed > settings.stash_velocity) {
        velocity = release;
        restore();
      } else {
        velocity = release;
        tuck(drag_side_);
      }
      return;
    }
    if (length(displacement) < 2 && length(release) < 1) {
      settleUnmovedGrab();
      return;
    }
    throwFrom(position, release, true);
  }

  void cancel() {
    if (phase != Phase::Dragging) return;
    velocity = {};
    if (drag_side_ != Side::None) tuck(drag_side_);
    else settleUnmovedGrab();
  }

  void throwFrom(Point origin, Point release, bool allow_stash) {
    position = origin;
    velocity = release;
    last_throw_ = Throw{origin, release, allow_stash};
    release_speed = length(release);
    dock_distance = length(origin - dockTarget(origin, {}));
    tucked = Side::None;
    const double left_overlap = area_.x - origin.x;
    const double right_overlap = origin.x + size.width - area_.x - area_.width;
    const bool horizontal = std::abs(release.x) > 1.6 * std::abs(release.y);
    const bool fling_left = origin.x < area_.x + 32 &&
        release.x < -settings.stash_velocity && horizontal;
    const bool fling_right = origin.x + size.width > area_.x + area_.width - 32 &&
        release.x > settings.stash_velocity && horizontal;
    const double tuck_distance = size.width * settings.stash_percent / 100;
    if (allow_stash && ((left_overlap > 0 && left_overlap >= tuck_distance) || fling_left)) {
      tuck(Side::Left);
    } else if (allow_stash && ((right_overlap > 0 && right_overlap >= tuck_distance) || fling_right)) {
      tuck(Side::Right);
    } else {
      const bool deliberate = release_speed <= settings.free_speed;
      const bool near_dock = dock_distance <= settings.snap_distance;
      if (settings.placement == Placement::Free ||
          (settings.placement == Placement::Smart && deliberate && !near_dock)) {
        decision = Decision::Keep;
        settle(clampVisible(origin), {}, Goal::Free);
      } else {
        decision = Decision::Dock;
        settle(dockDestination(origin, release), release, Goal::Dock);
      }
    }
  }

  void tuck(Side side) {
    decision = Decision::Tuck;
    if (side == Side::None)
      side = position.x + size.width / 2 < area_.x + area_.width / 2 ? Side::Left : Side::Right;
    const double y = std::clamp(position.y, area_.y + settings.margin,
        area_.y + area_.height - size.height - settings.margin);
    if (tucked == Side::None) {
      restore_point_ = {side == Side::Left ? area_.x + settings.margin :
          area_.x + area_.width - size.width - settings.margin, y};
    }
    restore_side_ = side;
    tucked = side;
    settle({side == Side::Left ? area_.x - size.width + settings.handle :
        area_.x + area_.width - settings.handle, y}, velocity, Goal::Stash);
  }

  void restore() {
    decision = Decision::Restore;
    tucked = Side::None;
    restore_point_.x = restore_side_ == Side::Left ? area_.x + settings.margin :
        area_.x + area_.width - size.width - settings.margin;
    restore_point_.y = std::clamp(restore_point_.y, area_.y + settings.margin,
        area_.y + area_.height - size.height - settings.margin);
    settle(restore_point_, velocity, Goal::Restore);
  }

  void replay() {
    if (!last_throw_) return;
    const auto sample = *last_throw_;
    throwFrom(sample.origin, sample.velocity, sample.allow_stash);
  }
  bool canReplay() const { return last_throw_.has_value(); }

  void retune(Settings next) {
    settings = next;
    if (phase == Phase::Dragging) return;
    if (tucked != Side::None) {
      tuck(tucked);
    } else if (goal_ == Goal::Restore) {
      restore_point_.x = restore_side_ == Side::Left ? area_.x + settings.margin :
          area_.x + area_.width - size.width - settings.margin;
      restore_point_.y = std::clamp(restore_point_.y, area_.y + settings.margin,
          area_.y + area_.height - size.height - settings.margin);
      settle(restore_point_, velocity, Goal::Restore);
    } else if (goal_ == Goal::Free) {
      settle(clampVisible(target), velocity, Goal::Free);
    } else {
      Point next_target = dockTarget(position, {});
      if (phase == Phase::Settling && last_throw_)
        next_target = dockDestination(last_throw_->origin, last_throw_->velocity);
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
  Rect area() const { return area_; }

 private:
  enum class Goal { Dock, Stash, Restore, Free };
  Point dockDestination(Point origin, Point release) const {
    const bool deliberate_attraction = settings.placement == Placement::Smart &&
        length(release) <= settings.free_speed;
    return dockTarget(origin, deliberate_attraction ? Point{} : release);
  }
  void settleUnmovedGrab() {
    velocity = {};
    if (start_settling_ && goal_ == Goal::Restore) {
      restore();
    } else if (start_settling_ && goal_ == Goal::Dock) {
      settle(dockTarget(target, {}), {}, Goal::Dock);
    } else {
      decision = Decision::Keep;
      release_speed = 0;
      Point destination = clampVisible(start_settling_ ? target : start_position_);
      dock_distance = length(destination - dockTarget(destination, {}));
      settle(destination, {}, Goal::Free);
    }
  }
  void constrainPresentation() {
    auto bound = [](double& coordinate, double& speed, double low, double high) {
      if (coordinate < low) { coordinate = low; speed = std::max(0.0, speed); }
      if (coordinate > high) { coordinate = high; speed = std::min(0.0, speed); }
    };
    bound(position.x, velocity.x, area_.x - size.width + settings.handle,
          area_.x + area_.width - settings.handle);
    bound(position.y, velocity.y, area_.y - size.height + settings.handle,
          area_.y + area_.height - settings.handle);
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
  struct Throw { Point origin, velocity; bool allow_stash; };
  Rect area_;
  Point offset_, start_position_, restore_point_;
  Side drag_side_ = Side::None;
  Side restore_side_ = Side::Right;
  bool start_settling_ = false;
  Goal goal_ = Goal::Dock;
  VelocityTracker tracker_;
  std::optional<Throw> last_throw_;
};

}  // namespace pip_motion
