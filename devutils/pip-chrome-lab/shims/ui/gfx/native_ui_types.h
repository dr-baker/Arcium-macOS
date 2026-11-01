#pragma once
#import <AppKit/AppKit.h>
// Only the Chromium object-wrapper boundary is replaced in the standalone host.
// The complete production controls, gestures and motion compile unchanged.
namespace gfx {
class NativeView {
 public:
  NativeView(NSView* view = nil) : view_(view) {}
  NSView* Get() const { return view_; }
 private:
  __strong NSView* view_;
};
class NativeViewAccessible {
 public:
  NativeViewAccessible(id value = nil) : value_(value) {}
  id Get() const { return value_; }
 private:
  __strong id value_;
};
}
