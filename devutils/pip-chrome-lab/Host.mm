#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#include "arcium_pip_native_controls.mm"

@interface LabPanel : NSPanel
@end
@implementation LabPanel
- (BOOL)canBecomeKeyWindow { return YES; }
- (BOOL)canBecomeMainWindow { return NO; }
@end
@interface LabBackdrop : NSView
@property(nonatomic,strong) NSImage* image;
@property(nonatomic) CGFloat lightness;
@end
@implementation LabBackdrop
- (void)drawRect:(NSRect)dirty {
  if (self.image) {
    [self.image drawInRect:self.bounds fromRect:NSZeroRect operation:NSCompositingOperationCopy fraction:1];
    return;
  }
  [[NSColor colorWithWhite:self.lightness alpha:1] setFill]; NSRectFill(self.bounds);
  [[NSColor colorWithWhite:1-self.lightness alpha:.35] setStroke];
  NSBezierPath* grid=[NSBezierPath bezierPath];
  for (CGFloat x=0;x<NSWidth(self.bounds);x+=32) { [grid moveToPoint:NSMakePoint(x,0)]; [grid lineToPoint:NSMakePoint(x,NSHeight(self.bounds))]; }
  for (CGFloat y=0;y<NSHeight(self.bounds);y+=32) { [grid moveToPoint:NSMakePoint(0,y)]; [grid lineToPoint:NSMakePoint(NSWidth(self.bounds),y)]; }
  [grid stroke];
}
@end
@interface Lab : NSObject<NSApplicationDelegate,NSWindowDelegate> {
  NSWindow* _card;
  NSWindow* _settings;
  LabBackdrop* _backdrop;
  std::unique_ptr<arcium::pip::NativeControls> _controls;
  arcium::pip::State _state;
  AVPlayer* _player;
  AVPlayerLayer* _video;
  id _videoObserver;
  NSTextField* _status;
  NSMutableDictionary<NSString*,NSSlider*>* _tuning;
}
@end
@implementation Lab
- (void)applicationDidFinishLaunching:(NSNotification*)note {
  _card=[[LabPanel alloc] initWithContentRect:NSMakeRect(100,180,640,360) styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];
  _card.releasedWhenClosed=NO; _card.delegate=self; _card.backgroundColor=NSColor.clearColor; _card.opaque=NO;
  _card.level=NSFloatingWindowLevel;
  _card.collectionBehavior=NSWindowCollectionBehaviorCanJoinAllSpaces|NSWindowCollectionBehaviorFullScreenAuxiliary;
  _card.acceptsMouseMovedEvents=YES;
  ((NSPanel*)_card).hidesOnDeactivate=NO;
  _card.contentView.wantsLayer=YES;
  _card.contentView.layer.cornerRadius=arcium::pip::geometry::kCornerRadius;
  _card.contentView.layer.cornerCurve=kCACornerCurveContinuous;
  _card.contentView.layer.masksToBounds=YES;
  _backdrop=[[LabBackdrop alloc] initWithFrame:_card.contentView.bounds];
  _backdrop.wantsLayer=YES;
  _backdrop.lightness=.65; _backdrop.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;
  NSString* image=[NSBundle.mainBundle pathForResource:@"reference" ofType:@"png"];
  if (image) _backdrop.image=[[NSImage alloc] initWithContentsOfFile:image];
  [_card.contentView addSubview:_backdrop];
  __weak Lab* weakSelf=self;
  _controls=std::make_unique<arcium::pip::NativeControls>(_card,[weakSelf](arcium::pip::Action action,double value){ [weakSelf action:action value:value]; });
  NSView* chrome=_controls->GetNativeView().Get();
  chrome.frame=_card.contentView.bounds; chrome.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;
  [_card.contentView addSubview:chrome];
  _state.can_play=_state.can_seek=_state.can_mute=true; _state.muted=true;
  _state.position=87; _state.duration=1493; _state.accent=0xFF8BA8E8;
  _state.title=u"You vs the Drainage She Told You Not to Worry About";
  _state.effects[static_cast<size_t>(arcium::pip::Effect::kEdgeShade)]=true;
  _controls->Update(_state);
  arcium::pip::Placement placement; placement.width=640;
  _controls->PreparePlacement(placement,nil,16./9.,{});
  [self buildSettings];
  [self tune:nil];
  [_card orderFront:nil]; [_settings makeKeyAndOrderFront:nil];
  [NSApp activateIgnoringOtherApps:YES];
}
- (void)action:(arcium::pip::Action)action value:(double)value {
  switch(action) {
    case arcium::pip::Action::kPlayPause: _state.playing=!_state.playing; if (_state.playing) [_player play]; else [_player pause]; break;
    case arcium::pip::Action::kSeek: _state.position=value*_state.duration; [_player seekToTime:CMTimeMakeWithSeconds(_state.position,600) toleranceBefore:kCMTimeZero toleranceAfter:kCMTimeZero]; break;
    case arcium::pip::Action::kBack15: _state.position=std::max(0.,_state.position-15); break;
    case arcium::pip::Action::kForward15: _state.position=std::min(_state.duration,_state.position+15); break;
    case arcium::pip::Action::kMute: _status.stringValue=@"Video stays muted in this lab"; break;
    case arcium::pip::Action::kReturn: _controls->RestorePlacementForHide(); [_card orderOut:nil]; _status.stringValue=@"Returned · Reset position brings the window back"; break;
    case arcium::pip::Action::kClose: _controls->RestorePlacementForHide(); [_card orderOut:nil]; _status.stringValue=@"Closed · Reset position brings the window back"; break;
    default: break;
  }
  if (action==arcium::pip::Action::kBack15 || action==arcium::pip::Action::kForward15)
    [_player seekToTime:CMTimeMakeWithSeconds(_state.position,600) toleranceBefore:kCMTimeZero toleranceAfter:kCMTimeZero];
  _controls->Update(_state);
}
- (void)buildSettings {
  _settings=[[NSWindow alloc] initWithContentRect:NSMakeRect(780,200,390,360) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
  _settings.title=@"PiP controls · live appearance"; _settings.releasedWhenClosed=NO;
  _tuning=[NSMutableDictionary dictionary];
  NSArray* names=@[@"Overlay dim",@"Top vignette",@"Corner radius",@"Title size",@"Test lightness"];
  if ([NSUserDefaults.standardUserDefaults integerForKey:@"Appearance schema"]<2) {
    [NSUserDefaults.standardUserDefaults setDouble:24 forKey:@"Corner radius"];
    [NSUserDefaults.standardUserDefaults setInteger:2 forKey:@"Appearance schema"];
  }
  double values[]={.24,.62,24,12,.65}, mins[]={0,0,6,9,0}, maxs[]={.6,.9,40,20,1};
  for (NSUInteger i=0;i<names.count;++i) {
    CGFloat y=300-i*45;
    NSTextField* label=[NSTextField labelWithString:names[i]]; label.frame=NSMakeRect(20,y,115,22); [_settings.contentView addSubview:label];
    NSSlider* slider=[NSSlider sliderWithValue:values[i] minValue:mins[i] maxValue:maxs[i] target:self action:@selector(tune:)];
    slider.identifier=names[i]; slider.frame=NSMakeRect(140,y,220,24); slider.continuous=YES;
    if ([NSUserDefaults.standardUserDefaults objectForKey:names[i]])
      slider.doubleValue=[NSUserDefaults.standardUserDefaults doubleForKey:names[i]];
    _tuning[names[i]]=slider; [_settings.contentView addSubview:slider];
  }
  NSButton* file=[NSButton buttonWithTitle:@"Open local video…" target:self action:@selector(openVideo:)]; file.frame=NSMakeRect(20,60,165,30); [_settings.contentView addSubview:file];
  NSButton* reset=[NSButton buttonWithTitle:@"Reset position" target:self action:@selector(reset:)]; reset.frame=NSMakeRect(200,60,165,30); [_settings.contentView addSubview:reset];
  _status=[NSTextField wrappingLabelWithString:@"Real production controls. Pinch, corner resize, hover and scrub. Video always muted."]; _status.frame=NSMakeRect(20,10,350,42); [_settings.contentView addSubview:_status];
}
- (void)tune:(id)sender {
  if (!_controls) return;
  NSView* overlay=_controls->GetNativeView().Get();
  if ([sender isKindOfClass:NSSlider.class]) {
    NSSlider* changed=sender;
    [NSUserDefaults.standardUserDefaults setDouble:changed.doubleValue forKey:changed.identifier];
  }
  NSView* shade=[overlay valueForKey:@"hoverShade"];
  shade.layer.backgroundColor=[NSColor colorWithWhite:0 alpha:_tuning[@"Overlay dim"].doubleValue].CGColor;
  NSView* top=[overlay valueForKey:@"vignetteView"];
  ((CAGradientLayer*)top.layer).colors=@[(__bridge id)NSColor.clearColor.CGColor,(__bridge id)[NSColor colorWithWhite:0 alpha:_tuning[@"Top vignette"].doubleValue].CGColor];
  CGFloat scale=std::clamp(std::min(NSWidth(overlay.bounds)/480.,NSHeight(overlay.bounds)/270.),.8,1.45);
  ((NSTextField*)[overlay valueForKey:@"title"]).font=[NSFont systemFontOfSize:_tuning[@"Title size"].doubleValue*scale weight:NSFontWeightSemibold];
  _card.contentView.layer.cornerRadius=_tuning[@"Corner radius"].doubleValue*scale;
  _backdrop.lightness=_tuning[@"Test lightness"].doubleValue;
  if ([sender isKindOfClass:NSSlider.class] && [((NSSlider*)sender).identifier isEqual:@"Test lightness"]) { _backdrop.image=nil; _video.hidden=YES; }
  _backdrop.needsDisplay=YES;
}
- (void)windowDidResize:(NSNotification*)note {
  if (_video) _video.frame=_backdrop.bounds;
  [self performSelector:@selector(tune:) withObject:nil afterDelay:0];
}
- (void)reset:(id)sender {
  _controls->RestorePlacementForHide();
  [_card setFrame:NSMakeRect(100,180,640,360) display:NO];
  _controls->Reanchor(16./9.,{}); [_card orderFront:nil];
  _status.stringValue=@"Reset · tuning unchanged";
}
- (void)openVideo:(id)sender {
  NSOpenPanel* picker=[NSOpenPanel openPanel]; picker.canChooseDirectories=NO; picker.allowsMultipleSelection=NO;
  [picker beginSheetModalForWindow:_settings completionHandler:^(NSModalResponse result){
    if (result!=NSModalResponseOK) return;
    if (self->_videoObserver) [self->_player removeTimeObserver:self->_videoObserver];
    self->_player=[AVPlayer playerWithURL:picker.URL]; self->_player.muted=YES;
    __weak Lab* weakSelf=self;
    self->_videoObserver=[self->_player addPeriodicTimeObserverForInterval:CMTimeMakeWithSeconds(.25,600) queue:dispatch_get_main_queue() usingBlock:^(CMTime time) {
      Lab* lab=weakSelf; if (!lab) return;
      const double duration=CMTimeGetSeconds(lab->_player.currentItem.duration);
      if (std::isfinite(duration) && duration>0) lab->_state.duration=duration;
      const double position=CMTimeGetSeconds(time);
      if (std::isfinite(position)) lab->_state.position=position;
      lab->_controls->Update(lab->_state);
    }];
    if (!self->_video) { self->_video=[AVPlayerLayer playerLayerWithPlayer:self->_player]; [self->_backdrop.layer addSublayer:self->_video]; }
    self->_video.player=self->_player; self->_video.hidden=NO; self->_video.frame=self->_backdrop.bounds;
    self->_video.videoGravity=AVLayerVideoGravityResizeAspect;
    self->_state.playing=false; self->_backdrop.image=nil;
    NSString* title=picker.URL.lastPathComponent;
    self->_state.title.resize(title.length);
    [title getCharacters:reinterpret_cast<unichar*>(self->_state.title.data()) range:NSMakeRange(0,title.length)];
    self->_controls->Update(self->_state);
    self->_status.stringValue=@"Local video loaded, paused and muted. Use Play.";
  }];
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication*)app { return YES; }
- (void)applicationWillTerminate:(NSNotification*)note { [_player pause]; if (_videoObserver) [_player removeTimeObserver:_videoObserver]; _controls.reset(); }
@end
int main() { @autoreleasepool {
  NSApplication* app=NSApplication.sharedApplication;
  [app setActivationPolicy:NSApplicationActivationPolicyRegular];
  Lab* delegate=[Lab new]; app.delegate=delegate;
  [app run];
} return 0; }
