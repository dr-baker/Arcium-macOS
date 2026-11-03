#pragma once

#include "Motion.hpp"

namespace pip_motion {

// A trackpad moves a held card in screen points. Cursor position is not reused
// after pickup: the window can move beneath a stationary pointer.
class Gestures {
 public:
  enum class Kind { None, Pan, Pinch };
  explicit Gestures(Motion& motion) : motion_(motion) {}
  Kind kind() const { return kind_; }

  void beginPan(double time) {
    if (kind_ == Kind::Pinch) return;
    point_ = motion_.position;
    motion_.begin(point_, time);
    kind_ = Kind::Pan;
  }
  void pan(Point delta, double time) {
    if (kind_ != Kind::Pan) return;
    point_ = point_ + delta;
    motion_.drag(point_, time);
  }
  void endPan(double time, bool cancelled = false) {
    if (kind_ != Kind::Pan) return;
    if (cancelled) motion_.cancel();
    else motion_.end(time);
    kind_ = Kind::None;
  }
  void beginPinch() {
    if (motion_.tucked != Side::None) return;
    if (kind_ == Kind::Pan) motion_.placeAt(motion_.position);
    before_ = motion_;
    center_ = {motion_.position.x + motion_.size.width / 2,
               motion_.position.y + motion_.size.height / 2};
    motion_.placeAt(motion_.position);
    kind_ = Kind::Pinch;
  }
  void magnify(double delta) {
    if (kind_ != Kind::Pinch || !std::isfinite(delta)) return;
    resize(motion_.size.width * std::max(.01, 1 + delta));
  }
  void endPinch(bool cancelled = false) {
    if (kind_ != Kind::Pinch) return;
    if (cancelled && before_) {
      const Settings settings = motion_.settings;
      const Rect area = motion_.area();
      const Rect physical = motion_.physicalArea();
      const Edges edges = motion_.exteriorEdges();
      motion_ = *before_;
      motion_.settings = settings;
      motion_.environment(area, motion_.size, edges, physical);
      motion_.resize(motion_.size);
      motion_.placeAt(motion_.position);
    }
    before_.reset();
    kind_ = Kind::None;
  }

 private:
  void resize(double requested) {
    const Rect area = motion_.area();
    const double aspect = motion_.size.width / motion_.size.height;
    const double maxWidth = std::max(1.0, std::min(area.width - 2 * motion_.settings.margin,
        (area.height - 2 * motion_.settings.margin) * aspect));
    const double width = std::clamp(requested, std::min(240.0, maxWidth), maxWidth);
    motion_.resize({width, width / aspect});
    motion_.placeAt({center_.x - width / 2, center_.y - width / aspect / 2});
  }
  Motion& motion_;
  Kind kind_ = Kind::None;
  Point point_, center_;
  std::optional<Motion> before_;
};

}  // namespace pip_motion
