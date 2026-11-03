#pragma once

#include "Motion.hpp"

namespace pip_motion {

enum class HintDirection { None, Left, Right, Up, Down, UpLeft, UpRight, DownLeft, DownRight };
enum class HintStyle { Hidden, Label, Symbol };
struct HintLayout { HintStyle style; Rect frame; };

inline HintDirection hintDirection(const ReleasePreview& preview, const Motion& motion) {
  if (preview.decision == Decision::Tuck)
    return preview.side == Side::Left ? HintDirection::Left : HintDirection::Right;
  if (preview.decision == Decision::Restore)
    return preview.side == Side::Left ? HintDirection::Right : HintDirection::Left;
  if (preview.decision == Decision::Keep) {
    const Point offset = preview.target - motion.position;
    const bool horizontal = std::abs(offset.x) > .5, vertical = std::abs(offset.y) > .5;
    if (horizontal && vertical) {
      if (offset.y > 0) return offset.x < 0 ? HintDirection::UpLeft : HintDirection::UpRight;
      return offset.x < 0 ? HintDirection::DownLeft : HintDirection::DownRight;
    }
    if (horizontal) return offset.x < 0 ? HintDirection::Left : HintDirection::Right;
    if (vertical) return offset.y < 0 ? HintDirection::Down : HintDirection::Up;
    return HintDirection::None;
  }
  if (preview.decision != Decision::Dock) return HintDirection::None;
  const Rect area = motion.area();
  const bool left = preview.target.x < area.x + (area.width - motion.size.width) / 2;
  if (motion.settings.docking == Docking::SideEdges)
    return left ? HintDirection::Left : HintDirection::Right;
  const bool down = preview.target.y < area.y + (area.height - motion.size.height) / 2;
  if (down) return left ? HintDirection::DownLeft : HintDirection::DownRight;
  return left ? HintDirection::UpLeft : HintDirection::UpRight;
}

// Position the hint within the part of the panel that is actually on screen.
inline HintLayout hintLayout(Point position, Size size, Rect area, double textWidth) {
  const double left = std::clamp(area.x - position.x, 0.0, size.width);
  const double right = std::clamp(area.x + area.width - position.x, 0.0, size.width);
  const double bottom = std::clamp(area.y - position.y, 0.0, size.height);
  const double top = std::clamp(area.y + area.height - position.y, 0.0, size.height);
  const double width = right - left, height = top - bottom;
  const double labelWidth = textWidth + 16;
  if (width >= labelWidth + 16 && height >= 36)
    return {HintStyle::Label, {right - labelWidth - 8, bottom + 8, labelWidth, 20}};
  if (width >= 10 && height >= 10) {
    const double extent = std::min({18.0, width, height});
    return {HintStyle::Symbol, {left + (width - extent) / 2,
                                bottom + (height - extent) / 2, extent, extent}};
  }
  return {HintStyle::Hidden, {}};
}

}  // namespace pip_motion
