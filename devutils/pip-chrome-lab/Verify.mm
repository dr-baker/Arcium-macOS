#import <Cocoa/Cocoa.h>
#include "arcium_pip_native_controls.mm"
#include <cstdio>
static int checks=0;
static void Check(bool pass,const char* reason) { ++checks; if(!pass) { std::fprintf(stderr,"FAIL: %s\n",reason); std::exit(1); } }
static void Exception(NSException* e) { std::fprintf(stderr,"EXCEPTION: %s\n%s\n",e.description.UTF8String,e.callStackSymbols.description.UTF8String); }
int main() { @autoreleasepool {
  NSSetUncaughtExceptionHandler(Exception);
  std::fprintf(stderr,"checkpoint: native initialization\n");
  [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
  using namespace arcium::pip;
  geometry::Rect anchor{400,300,480,270}, area{0,0,2200,1400};
  double previous=0; bool oldDrift=false;
  for(int i=0;i<1000;++i) {
    double w=400+i*.25,h=w/(16./9.); double x=640-w/2,y=435-h/2;
    oldDrift |= std::abs((std::round(x)+std::round(x+w))/2-640)>.1;
    auto r=geometry::CenteredIntegralResize(anchor,{x,y,w,h},area);
    Check(r.x+r.width/2==640 && r.y+r.height/2==435,"stationary pinch center");
    Check(r.width>=previous,"monotonic pinch growth"); previous=r.width;
    Check(r.x==std::round(r.x) && r.y==std::round(r.y),"integral native origins");
  }
  Check(oldDrift,"counterexample reproduces old center drift");
  for (auto start : {geometry::Rect{22,22,640,360}, geometry::Rect{538,22,640,360},
                     geometry::Rect{22,518,640,360}, geometry::Rect{538,518,640,360}}) {
    for (double width : {400.,800.,1190.}) {
      pip_motion::Motion model;
      model.settings.margin=21.93;
      model.environment({0,0,1200,900},{640,360});
      const auto accepted=geometry::CenteredIntegralResize(start,{0,0,width,width/(16./9.)},
          geometry::IntegralResizeArea({0,0,1200,900},model.settings.margin),
          {100,100,2000,2000});
      model.resize({accepted.width,accepted.height}); model.placeAt({accepted.x,accepted.y});
      Check(model.position.x==accepted.x && model.position.y==accepted.y,"edge release does not re-clamp accepted origin");
      Check(model.size.width==accepted.width && model.size.height==accepted.height,"max-fit release does not shrink accepted size");
    }
  }
  std::fprintf(stderr,"checkpoint: geometry passed, creating hidden window\n");
  for (auto start : {geometry::Rect{400,300,481,271}, geometry::Rect{400,300,480,270}}) {
    for (double width : {1., 284., 400., 481., 960., 3000.}) {
      const auto frame=geometry::CenteredIntegralResize(start,{0,0,width,width/(16./9.)},{-5000,-5000,12000,12000});
      Check(frame.width>=geometry::SizeLimits{}.minimum_width,"pinch minimum size");
      Check(frame.width<=geometry::SizeLimits{}.maximum_width,"pinch maximum size");
      Check(frame.x+frame.width/2==start.x+start.width/2,"odd and even anchors keep center");
    }
  }
  NSWindow* window=[[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,640,360) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
  window.releasedWhenClosed=NO;
  std::fprintf(stderr,"checkpoint: constructing production controls\n");
  int returns=0;
  NativeControls controls(window,[&returns](Action action,double){ if (action==Action::kReturn) ++returns; });
  auto* overlay=(ArciumPiPNativeOverlay*)controls.GetNativeView().Get();
  overlay.frame=window.contentView.bounds; [window.contentView addSubview:overlay];
  State state; state.can_play=state.can_seek=true; state.duration=100; state.title=u"White title without a pill";
  controls.Update(state); [overlay setValue:@YES forKey:@"nativeVisible"]; [overlay refreshChrome];
  for (NSSize size : {NSMakeSize(284,160),NSMakeSize(480,270),NSMakeSize(1200,675),NSMakeSize(284,600)}) {
    overlay.frame=NSMakeRect(0,0,size.width,size.height); [overlay layoutSubtreeIfNeeded];
    NSView* shade=[overlay valueForKey:@"hoverShade"]; NSView* vignette=[overlay valueForKey:@"vignetteView"];
    NSTextField* title=[overlay valueForKey:@"title"];
    Check(NSEqualSizes(shade.frame.size,size),"full-video overlay");
    Check(NSMaxY(vignette.frame)==size.height,"vignette at top only");
    Check(NSHeight(vignette.frame)<size.height,"vignette does not cover whole video");
    NSView* left=[overlay valueForKey:@"returnGlass"]; NSView* right=[overlay valueForKey:@"tuckGlass"];
    const CGFloat gap=6*geometry::ControlScale(size.width,size.height);
    Check(std::abs(NSMinX(title.frame)-NSMaxX(left.frame)-gap)<.01,"title uses left space");
    Check(std::abs(NSMaxX(title.frame)-NSMinX(right.frame)+gap)<.01,"title uses right space");
    Check(std::abs(geometry::CornerRadius(size.width,size.height)-NSMidX(left.frame))<.01,"button and window corners concentric");
    Check(title.textColor==NSColor.whiteColor,"white title");
    auto* slider=(ArciumPiPSlider*)[overlay valueForKey:@"slider"];
    auto* cell=(ArciumPiPSliderCell*)slider.cell;
    Check(NSWidth([cell knobRectFlipped:slider.flipped])>=9.6,"scrubber scales with controls");
    [slider setTrackingThumb:YES];
    NSView* thumb=[slider valueForKey:@"thumbHost"];
    Check(!thumb.hidden,"glass pickup shown");
    Check([thumb hitTest:NSMakePoint(1,1)]==nil,"thumb leaves native tracking alone");
    Check(NSWidth(thumb.frame)>NSWidth([cell knobRectFlipped:slider.flipped]),"pickup expands thumb");
    [slider setTrackingThumb:NO];
  }
  overlay.frame=window.contentView.bounds;
  [overlay applyPinch:1.0/640 ended:NO cancelled:NO];
  [overlay flushResizeFrame];
  const NSRect lastPinch=window.frame;
  [overlay applyPinch:0 ended:YES cancelled:NO];
  Check(NSEqualRects(window.frame,lastPinch),"pinch release retains last displayed geometry");
  const NSRect beforeCancel=window.frame;
  [overlay applyPinch:-.08 ended:NO cancelled:NO]; [overlay flushResizeFrame];
  Check(NSWidth(window.frame)<NSWidth(beforeCancel),"real pinch shrinks");
  [overlay applyPinch:0 ended:NO cancelled:YES];
  Check(NSEqualRects(window.frame,beforeCancel),"cancel restores exact native frame");
  const NSRect visible=NSScreen.mainScreen.visibleFrame;
  for (int corner=0;corner<4;++corner) {
    const CGFloat x=(corner&1) ? NSMaxX(visible)-662 : NSMinX(visible)+22;
    const CGFloat y=(corner&2) ? NSMaxY(visible)-382 : NSMinY(visible)+22;
    NSWindow* edge=[[NSWindow alloc] initWithContentRect:NSMakeRect(x,y,640,360) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    edge.releasedWhenClosed=NO;
    NativeControls edgeControls(edge,[](Action,double){});
    auto* view=(ArciumPiPNativeOverlay*)edgeControls.GetNativeView().Get();
    [edge.contentView addSubview:view]; edgeControls.Update(state);
    [view applyPinch:.25 ended:NO cancelled:NO]; [view flushResizeFrame];
    const NSRect displayed=edge.frame;
    [view applyPinch:0 ended:YES cancelled:NO];
    Check(NSEqualRects(edge.frame,displayed),"real edge pinch retains frame on release");
  }
  [overlay setValue:@YES forKey:@"magnifying"]; [overlay refreshChrome];
  Check(((NSView*)[overlay valueForKey:@"hoverShade"]).hidden,"overlay suppressed during pinch");
  Check(((NSView*)[overlay valueForKey:@"vignetteView"]).hidden,"vignette suppressed during pinch");
  Check(((NSView*)[overlay valueForKey:@"title"]).hidden,"title suppressed during pinch");
  [overlay setValue:@NO forKey:@"magnifying"];
  [overlay pointerInteraction];
  controls.FocusControls(false);  // Delayed host focus after a pointer press.
  [overlay performSelector:@selector(mouseExited:) withObject:nil];
  Check(![overlay keepsKeyboardControlsVisible],"pointer focus does not become a keyboard pin");
  Check(((NSView*)[overlay valueForKey:@"glassContainer"]).hidden,"pointer exit hides complete native button group");
  controls.ReleaseFocus();
  NSTimer* expired=[overlay valueForKey:@"hideTimer"]; [expired invalidate];
  state.show_controls=false; controls.Update(state);
  state.show_controls=true; controls.Update(state);
  Check(((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"state-driven reveal always has a dismissal timer");
  state.title=u"A very long video title that should fade rather than use an ellipsis and scroll on hover to expose the entire title";
  controls.Update(state); [overlay setValue:@YES forKey:@"mouseInside"]; [overlay setValue:@YES forKey:@"nativeVisible"];
  [overlay refreshChrome]; [overlay layoutSubtreeIfNeeded];
  auto* title=(ArciumPiPTitle*)[overlay valueForKey:@"title"];
  Check(title.lineBreakMode==NSLineBreakByClipping,"no title ellipsis");
  Check(title.layer.mask!=nil,"overflow uses progressive fade");
  Check([title accessibilityRole]==NSAccessibilityButtonRole,"title exposes return action");
  [title performSelector:@selector(mouseEntered:) withObject:nil];
  CATextLayer* text=[title valueForKey:@"textLayer"];
  if (!ReduceMotion()) {
    Check([text animationForKey:@"marquee"]!=nil,"hover starts compositor marquee");
    CAKeyframeAnimation* fade=(CAKeyframeAnimation*)[title.layer.mask animationForKey:@"fadeLeading"];
    Check([fade.values[2][2] doubleValue]==1,"terminal marquee pause reveals trailing characters");
  }
  Check(!((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"marquee keeps controls while reading");
  [title performSelector:@selector(mouseExited:) withObject:nil];
  Check(((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"leaving title resumes dismissal");
  Check([text animationForKey:@"marquee"]==nil,"exit stops marquee");
  [title performSelector:@selector(mouseEntered:) withObject:nil];
  title.stringValue=@"Short";
  Check(title.layer.mask==nil,"short title needs no fade");
  Check(((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"hovered long-to-short title resumes dismissal");
  [(NSTimer*)[overlay valueForKey:@"hideTimer"] fire];
  Check(((NSView*)[overlay valueForKey:@"glassContainer"]).hidden,"title update timer actually dismisses buttons");
  [overlay setValue:@YES forKey:@"nativeVisible"]; [overlay refreshChrome];
  [title performSelector:@selector(mouseEntered:) withObject:nil];
  title.stringValue=@"A very long video title that needs the full marquee to be read while hovered";
  Check(!((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"hovered short-to-long title pauses dismissal");
  NSSize oldSize=title.frame.size;
  [title setFrameSize:NSMakeSize(3000,oldSize.height)];
  Check(((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"fitting hovered title after resize resumes dismissal");
  [title setFrameSize:oldSize];
  Check(!((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"overflow after resize pauses dismissal");
  title.hidden=YES;
  Check(((NSTimer*)[overlay valueForKey:@"hideTimer"]).valid,"hiding a hovered title resumes dismissal");
  title.hidden=NO; title.stringValue=@"Short";
  NSPoint center=[title convertPoint:NSMakePoint(NSMidX(title.bounds),NSMidY(title.bounds)) toView:nil];
  NSEvent* down=[NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:center modifierFlags:0 timestamp:1 windowNumber:window.windowNumber context:nil eventNumber:1 clickCount:1 pressure:1];
  NSEvent* up=[NSEvent mouseEventWithType:NSEventTypeLeftMouseUp location:center modifierFlags:0 timestamp:1.1 windowNumber:window.windowNumber context:nil eventNumber:2 clickCount:1 pressure:0];
  [title mouseDown:down];
  Check(returns==0,"title waits for click release");
  [title mouseUp:up];
  __block BOOL delivered=NO;
  dispatch_async(dispatch_get_main_queue(), ^{ delivered=YES; });
  for (int turn=0;turn<50 && !delivered;++turn)
    CFRunLoopRunInMode(kCFRunLoopDefaultMode,.01,false);
  Check(delivered,"main queue delivers native actions");
  Check(returns==1,"clicking title returns video to tab");

  std::printf("PASS %d complete-production AppKit and geometry checks; no window ordering/activation\n",checks);
} return 0; }
