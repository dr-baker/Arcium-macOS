#import <Cocoa/Cocoa.h>
#include "arcium_pip_native_controls.mm"
#include <cstdio>
@interface HiddenGesturePanel : NSPanel
@property BOOL admitGestureInput;
@property BOOL requestedKey;
@end
@implementation HiddenGesturePanel
- (BOOL)canBecomeKeyWindow { return YES; }
- (BOOL)isVisible { return self.admitGestureInput || super.visible; }
- (void)makeKeyWindow { self.requestedKey=YES; }
@end
@interface TestPinchRecognizer : NSMagnificationGestureRecognizer
@property NSGestureRecognizerState testState;
@end
@implementation TestPinchRecognizer
- (NSGestureRecognizerState)state { return self.testState; }
@end
@interface TestIndirectTouch : NSTouch
@property NSPoint point;
@property(nonatomic,strong) id token;
@end
@implementation TestIndirectTouch
- (NSTouchType)type { return NSTouchTypeIndirect; }
- (NSPoint)normalizedPosition { return self.point; }
- (NSSize)deviceSize { return NSMakeSize(100,60); }
- (id)identity { return self.token; }
- (id)device { return @"test-trackpad"; }
@end
@interface TestTouchEvent : NSEvent
@property(nonatomic,strong) NSSet<NSTouch*>* pair;
@property BOOL cancelTouches;
@property NSEventType kind;
@end
@implementation TestTouchEvent
- (NSEventType)type { return self.kind==0 ? NSEventTypeGesture : self.kind; }
- (NSSet<NSTouch*>*)touchesMatchingPhase:(NSTouchPhase)phase inView:(NSView*)view {
  if (phase==NSTouchPhaseCancelled) return self.cancelTouches ? self.pair : NSSet.set;
  return self.cancelTouches ? NSSet.set : self.pair;
}
@end
@interface TrackingTestEvent : NSEvent
@property(nonatomic,strong) NSTrackingArea* area;
@property NSEventType kind;
@end
@implementation TrackingTestEvent
- (NSEventType)type { return self.kind; }
- (NSTrackingArea*)trackingArea { return self.area; }
@end
@interface HoverMagnifyEvent : NSEvent
@property(nonatomic,weak) NSWindow* targetWindow;
@property CGFloat delta;
@property NSEventPhase eventPhase;
@property NSPoint targetPoint;
@end
@implementation HoverMagnifyEvent
- (NSEventType)type { return NSEventTypeMagnify; }
- (NSWindow*)window { return self.targetWindow; }
- (NSPoint)locationInWindow { return self.targetPoint; }
- (CGFloat)magnification { return self.delta; }
- (NSEventPhase)phase { return self.eventPhase; }
@end
static int checks=0;
static void Check(bool pass,const char* reason) { ++checks; if(!pass) { std::fprintf(stderr,"FAIL: %s\n",reason); std::exit(1); } }
static void Exception(NSException* e) { std::fprintf(stderr,"EXCEPTION: %s\n%s\n",e.description.UTF8String,e.callStackSymbols.description.UTF8String); }
int main() { @autoreleasepool {
  NSSetUncaughtExceptionHandler(Exception);
  std::fprintf(stderr,"checkpoint: native initialization\n");
  [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
  using namespace arcium::pip;
  pip_motion::TouchPinch touchModel;
  touchModel.sample({0,0},{40,0});
  auto firstTouch=touchModel.sample({-1,0},{41,0});
  Check(firstTouch.began && std::abs(firstTouch.delta-.05)<1e-9,"separation starts pinch with full threshold delta");
  auto nextTouch=touchModel.sample({0,0},{40,0});
  Check(!nextTouch.began && nextTouch.delta<0,"reversing separation shrinks smoothly");
  touchModel.reset();
  for (int i=0;i<40;++i) {
    touchModel.sample({double(i)*2,10},{40+double(i)*2+.1*std::sin(i),10});
    Check(!touchModel.active(),"parallel two-finger pan and slight finger jitter do not zoom");
  }
  Check(touchModel.sample({78,10},{128,10}).began,"pinch can begin after parallel pan");
  touchModel.reset(); touchModel.sample({0,0},{40,0});
  Check(touchModel.sample({0,0},{42,0}).began,"one stationary finger still permits pinch");
  touchModel.reset(); touchModel.sample({0,0},{0,0});
  Check(!touchModel.active(),"coincident contacts do not produce scale division");
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
  HiddenGesturePanel* window=[[HiddenGesturePanel alloc] initWithContentRect:NSMakeRect(100,100,640,360) styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];
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

  [overlay setValue:@YES forKey:@"mouseInside"];
  [overlay pointerInteraction];
  controls.FocusControls(false);
  [overlay pointerInteraction];
  Check(window.firstResponder==overlay,"pointer control release keeps gesture responder in overlay");
  [window makeFirstResponder:window.contentView];
  [overlay performSelector:@selector(mouseEntered:) withObject:nil];
  Check(window.requestedKey,"hover requests gesture key window");
  Check(window.firstResponder==overlay,"hover selects overlay as gesture responder");
  [overlay updateTrackingAreas];
  NSTrackingArea* tracking=[overlay valueForKey:@"tracking"];
  for (int i=0;i<4;++i) { [overlay refreshChrome]; [overlay layoutSubtreeIfNeeded]; [overlay updateTrackingAreas]; }
  Check([overlay valueForKey:@"tracking"]==tracking,"relayout preserves live overlay hover tracking");
  [title updateTrackingAreas];
  NSTrackingArea* titleTracking=[title valueForKey:@"titleTracking"];
  [title updateTrackingAreas];
  Check([title valueForKey:@"titleTracking"]==titleTracking,"relayout preserves live title hover tracking");
  auto* trackingEvent=[TrackingTestEvent new];
  trackingEvent.kind=NSEventTypeMouseExited;
  trackingEvent.area=[[NSTrackingArea alloc] initWithRect:NSZeroRect options:NSTrackingMouseEnteredAndExited|NSTrackingActiveAlways owner:title userInfo:nil];
  [overlay mouseExited:trackingEvent];
  Check([[overlay valueForKey:@"mouseInside"] boolValue],"child tracking exit cannot clear whole-card hover");
  [overlay performSelector:@selector(mouseExited:) withObject:nil];
  trackingEvent.kind=NSEventTypeMouseEntered;
  [overlay mouseEntered:trackingEvent];
  Check(![[overlay valueForKey:@"mouseInside"] boolValue],"child tracking enter cannot reveal whole-card chrome");
  const NSRect savedWindowFrame=window.frame;
  [window setFrameOrigin:NSMakePoint(-10000,-10000)];
  trackingEvent.area=tracking;
  [overlay mouseEntered:trackingEvent];
  Check(![[overlay valueForKey:@"mouseInside"] boolValue],"stale own enter outside physical window is rejected");
  NSPoint physical=NSEvent.mouseLocation;
  [window setFrameOrigin:NSMakePoint(physical.x-200,physical.y-100)];
  [overlay performSelector:@selector(mouseEntered:) withObject:nil];
  trackingEvent.kind=NSEventTypeMouseExited;
  [overlay mouseExited:trackingEvent];
  Check([[overlay valueForKey:@"mouseInside"] boolValue],"stale own exit inside physical window preserves gesture focus");
  [window setFrame:savedWindowFrame display:NO];
  window.admitGestureInput=YES;
  Check([overlay acceptsGestureInput],"attached nonactivating panel admits gesture input");
  auto* recognizer=[TestPinchRecognizer new];
  recognizer.testState=NSGestureRecognizerStateBegan; recognizer.magnification=0;
  [overlay recognizePinch:recognizer];
  const NSRect beforeRouted=window.frame;
  recognizer.testState=NSGestureRecognizerStateChanged; recognizer.magnification=.1;
  [overlay recognizePinch:recognizer]; [overlay flushResizeFrame];
  Check(NSWidth(window.frame)>NSWidth(beforeRouted),"recognizer action grows nonactivating panel");
  recognizer.testState=NSGestureRecognizerStateChanged; recognizer.magnification=-.2;
  [overlay recognizePinch:recognizer]; [overlay flushResizeFrame];
  Check(NSWidth(window.frame)<NSWidth(beforeRouted),"recognizer action shrinks nonactivating panel");
  recognizer.testState=NSGestureRecognizerStateEnded; recognizer.magnification=0;
  [overlay recognizePinch:recognizer];
  Check(![[overlay valueForKey:@"magnifying"] boolValue],"recognizer end releases pinch ownership");
  window.admitGestureInput=NO;
  Check(!window.visible,"gesture fixture never ordered native panel");
  HiddenGesturePanel* hoverWindow=[[HiddenGesturePanel alloc] initWithContentRect:NSMakeRect(100,100,480,270)
      styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];
  hoverWindow.releasedWhenClosed=NO; hoverWindow.admitGestureInput=YES;
  NativeControls hoverControls(hoverWindow,[](Action,double){});
  auto* hover=(ArciumPiPNativeOverlay*)hoverControls.GetNativeView().Get();
  hover.frame=hoverWindow.contentView.bounds; [hoverWindow.contentView addSubview:hover];
  hoverControls.Update(state);
  [hover performSelector:@selector(mouseEntered:) withObject:nil];
  Check(hoverWindow.firstResponder==hover,"fresh hover takes gesture focus without click");
  auto* magnify=[HoverMagnifyEvent new]; magnify.targetWindow=hoverWindow; magnify.targetPoint=NSMakePoint(200,100);
  const NSRect beforeHoverPinch=hoverWindow.frame;
  magnify.eventPhase=NSEventPhaseBegan; magnify.delta=0; [hover magnifyWithEvent:magnify];
  magnify.eventPhase=NSEventPhaseChanged; magnify.delta=.15; [hover magnifyWithEvent:magnify]; [hover flushResizeFrame];
  Check(NSWidth(hoverWindow.frame)>NSWidth(beforeHoverPinch),"hover-only raw pinch grows without any click");
  magnify.delta=-.25; [hover magnifyWithEvent:magnify]; [hover flushResizeFrame];
  Check(NSWidth(hoverWindow.frame)<NSWidth(beforeHoverPinch),"hover-only raw pinch shrinks without any click");
  magnify.eventPhase=NSEventPhaseEnded; magnify.delta=0; [hover magnifyWithEvent:magnify];
  Check(![[hover valueForKey:@"magnifying"] boolValue],"hover-only fallback finishes pinch ownership");
  Check(hover.gestureRecognizers.firstObject.delaysMagnificationEvents,"recognized gestures delay raw fallback to avoid duplicate resize");
  hoverWindow.admitGestureInput=NO;
  const NSRect hiddenFrame=hoverWindow.frame;
  magnify.eventPhase=NSEventPhaseChanged; magnify.delta=.2; [hover magnifyWithEvent:magnify]; [hover flushResizeFrame];
  Check(NSEqualRects(hoverWindow.frame,hiddenFrame),"hidden hover fallback rejects input");

  // Match the live hover route using indirect touch samples, without any click
  // or synthesized Magnify event. Windows remain unordered throughout.
  NSPoint pointer=NSEvent.mouseLocation;
  [hoverWindow setFrame:NSMakeRect(pointer.x-200,pointer.y-100,480,270) display:NO];
  hoverWindow.admitGestureInput=YES; hover.frame=hoverWindow.contentView.bounds;
  auto* ta=[TestIndirectTouch new]; ta.token=[NSObject new]; ta.point=NSMakePoint(.3,.5);
  auto* tb=[TestIndirectTouch new]; tb.token=[NSObject new]; tb.point=NSMakePoint(.7,.5);
  auto* touches=[TestTouchEvent new]; touches.pair=[NSSet setWithObjects:ta,tb,nil];
  const NSRect beforeTouches=hoverWindow.frame;
  Check(![hover consumeTouchPinch:touches],"hover touch pair waits for pinch intent and preserves pan");
  ta.point=NSMakePoint(.2,.5); tb.point=NSMakePoint(.8,.5);
  Check([hover consumeTouchPinch:touches],"hover separation claims pinch without native magnification");
  [hover flushResizeFrame];
  Check(NSWidth(hoverWindow.frame)>NSWidth(beforeTouches),"indirect hover pinch grows window");
  Check(!hover.gestureRecognizers.firstObject.enabled,"native recognizer is suspended while direct touch owns pinch");
  const NSRect once=hoverWindow.frame;
  magnify.delta=.5;
  Check([hover consumeMagnify:magnify],"duplicate native magnification is consumed");
  [hover flushResizeFrame];
  Check(NSEqualRects(once,hoverWindow.frame),"duplicate native magnification does not resize twice");
  ta.point=NSMakePoint(.35,.5); tb.point=NSMakePoint(.65,.5);
  Check([hover consumeTouchPinch:touches],"direct touch pinch keeps ownership while shrinking");
  [hover flushResizeFrame];
  Check(NSWidth(hoverWindow.frame)<NSWidth(beforeTouches),"indirect hover pinch shrinks window");
  touches.pair=[NSSet setWithObject:ta];
  Check([hover consumeTouchPinch:touches],"lifting a finger ends the owned pinch");
  Check([[hover valueForKey:@"consumeMomentum"] boolValue],"pinch completion consumes inertia from a preceding pan");
  Check(![[hover valueForKey:@"magnifying"] boolValue] && hover.gestureRecognizers.firstObject.enabled,"finger lift restores native recognizer and releases pinch");
  touches.pair=[NSSet setWithObjects:ta,tb,nil];
  [hover stopMotion];
  pointer=NSEvent.mouseLocation;
  [hoverWindow setFrameOrigin:NSMakePoint(pointer.x-NSWidth(hoverWindow.frame)/2,pointer.y-NSHeight(hoverWindow.frame)/2)];
  hover.frame=hoverWindow.contentView.bounds;
  Check(PointerInsideView(hover),"next hover gesture starts under actual pointer");
  Check(![hover consumeTouchPinch:touches],"next pair starts a fresh baseline");
  const NSRect cancelBase=hoverWindow.frame;
  ta.point=NSMakePoint(.25,.5); tb.point=NSMakePoint(.75,.5);
  Check([hover consumeTouchPinch:touches],"next pinch begins independently"); [hover flushResizeFrame];
  touches.kind=NSEventTypeEndGesture;
  Check([hover consumeTouchPinch:touches] && [[hover valueForKey:@"magnifying"] boolValue],"native pan end cannot cut off the same fingers pinching");
  touches.kind=NSEventTypeGesture;
  touches.cancelTouches=YES;
  Check([hover consumeTouchPinch:touches],"cancelled direct pinch stays consumed");
  Check(NSEqualRects(hoverWindow.frame,cancelBase),"touch cancellation restores exact prior frame");
  touches.cancelTouches=NO; ta.point=NSMakePoint(.3,.5); tb.point=NSMakePoint(.7,.5);
  [hover stopMotion];
  pointer=NSEvent.mouseLocation;
  [hoverWindow setFrameOrigin:NSMakePoint(pointer.x-NSWidth(hoverWindow.frame)/2,pointer.y-NSHeight(hoverWindow.frame)/2)];
  [hover consumeTouchPinch:touches]; ta.point=NSMakePoint(.2,.5); tb.point=NSMakePoint(.8,.5); [hover consumeTouchPinch:touches];
  hoverControls.RestorePlacementForHide();
  Check(![[hover valueForKey:@"magnifying"] boolValue] && hover.gestureRecognizers.firstObject.enabled,"hide rolls back direct pinch and restores event ownership");
  [hoverWindow setFrameOrigin:NSMakePoint(-10000,-10000)];
  Check(![hover consumeTouchPinch:touches],"indirect pair outside card cannot claim pinch");
  hoverWindow.admitGestureInput=NO;

  std::printf("PASS %d complete-production AppKit and geometry checks; no window ordering/activation\n",checks);
} return 0; }
