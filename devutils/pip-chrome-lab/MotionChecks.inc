// Native frame callbacks may synchronously hide, reopen or replace the model.
static void CheckMotionBoundaries() {
  using namespace arcium::pip;
  const IMP oldOrder=method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),(IMP)NoLifecycleOrder);
  for (bool effects : {false,true}) for (int replacement=0;replacement<4;++replacement) {
    @autoreleasepool {
      auto* panel=LifecycleWindow(NSMakeRect(300,300,640,360));panel.admitted=YES;
      NativeControls controls(panel,[](Action,double){});
      auto* view=(ArciumPiPNativeOverlay*)controls.GetNativeView().Get();[panel.contentView addSubview:view];
      State state;state.effects.fill(effects);controls.Update(state);
      auto* pan=[PanTestEvent new];pan.targetWindow=panel;pan.targetPoint=NSMakePoint(200,100);
      pan.eventPhase=NSEventPhaseBegan;pan.dx=12;pan.dy=-8;
      Check([view consumeScroll:pan],"motion probe admits native pan");
      [view renderMotionAt:NSProcessInfo.processInfo.systemUptime];
      __block BOOL injected=NO;
      __block uint64_t nextGeneration=0;
      __block NSRect nextFrame=NSZeroRect;
      __weak LifecyclePanel* weakPanel=panel;
      panel.frameHook=^{
        injected=YES;
        if(replacement==2) {
          [view stopMotion];[view ensureMotion];
        } else {
          [view prepareForHide];
          if(replacement==1) {
            weakPanel.admitted=NO;
            Placement placement;placement.width=480;
            [view preparePlacement:placement opener:nil aspect:16./9. limits:{}];
            weakPanel.admitted=YES;[view ensureMotion];
          } else if(replacement==3) [view invalidate];
        }
        nextGeneration=[[view valueForKey:@"motionGeneration"] unsignedLongLongValue];
        nextFrame=weakPanel.frame;
      };
      pan.eventPhase=NSEventPhaseChanged;pan.dx=36;pan.dy=-20;
      Check([view consumeScroll:pan],"motion probe accepts continued two-axis displacement");
      [CATransaction begin];[CATransaction setAnimationDuration:7];
      [view renderMotionAt:NSProcessInfo.processInfo.systemUptime];
      Check([CATransaction animationDuration]==7,"reentrant motion exits balance their Core Animation transaction");
      [CATransaction commit];
      Check(injected,"motion probe reaches the actual native frame setter");
      Check([[view valueForKey:@"motionGeneration"] unsignedLongLongValue]==nextGeneration && NSEqualRects(panel.frame,nextFrame),"old motion frame leaves the replacement geometry and ownership intact");
      if(replacement==0 || replacement==3) {
        Check(panel.alphaValue==0 && [view valueForKey:@"pressureFeedback"]==nil,"hidden motion frame cannot recreate pressure windows or reveal the parent");
      } else {
        Check(![[view valueForKey:@"hiding"] boolValue] && panel.alphaValue==1,"replacement motion remains available and visible");
        [view renderMotionAt:NSProcessInfo.processInfo.systemUptime];
        Check(NSEqualRects(panel.frame,nextFrame),"fresh replacement motion renders its own geometry");
      }
      panel.admitted=NO;
    }
  }
  method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),oldOrder);
}
