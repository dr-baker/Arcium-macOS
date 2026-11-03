#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
static void Log(NSString *kind, NSEvent *event, double value) {
  NSPoint local=event?event.locationInWindow:NSZeroPoint, global=NSEvent.mouseLocation;
  NSDictionary *d=@{@"at":@([NSDate date].timeIntervalSince1970),@"kind":kind,@"type":@(event?event.type:0),@"local_x":@(local.x),@"local_y":@(local.y),@"global_x":@(global.x),@"global_y":@(global.y),@"value":@(value)};
  NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil]; fwrite(j.bytes,1,j.length,stdout); fputc('\n',stdout); fflush(stdout);
}
@interface ProbeSlider:NSSlider @end
@implementation ProbeSlider
-(BOOL)acceptsFirstMouse:(NSEvent*)e{return YES;}
-(void)mouseDown:(NSEvent*)e {Log(@"slider-down",e,self.doubleValue);[super mouseDown:e];Log(@"slider-track-return",nil,self.doubleValue);}
@end
@interface ProbeDelegate:NSObject<NSApplicationDelegate>
@property NSWindow *window;
@property ProbeSlider *slider;
@property NSTextField *valueLabel;
@property id monitor;
@end
@implementation ProbeDelegate
-(void)applicationDidFinishLaunching:(NSNotification*)n {
 NSScreen *screen=nil;for(NSScreen *s in NSScreen.screens)if(CGDisplayIsBuiltin([s.deviceDescription[@"NSScreenNumber"] unsignedIntValue]))screen=s;
 if(!screen){Log(@"no-builtin-screen",nil,0);[NSApp terminate:nil];return;}
 NSRect area=screen.visibleFrame, frame=NSMakeRect(NSMinX(area)+60,NSMaxY(area)-310,600,240);
 self.window=[[NSWindow alloc]initWithContentRect:frame styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO screen:screen];
 self.window.title=@"Native AppKit drag diagnostic";self.window.releasedWhenClosed=NO;
 NSTextField *heading=[NSTextField labelWithString:@"AppKit NSSlider control. No browser or media."];
 heading.frame=NSMakeRect(24,180,550,24);[self.window.contentView addSubview:heading];
 self.slider=[[ProbeSlider alloc]initWithFrame:NSMakeRect(24,110,552,32)];self.slider.minValue=0;self.slider.maxValue=100;self.slider.doubleValue=20;self.slider.continuous=YES;self.slider.target=self;self.slider.action=@selector(changed:);[self.slider setAccessibilityLabel:@"Native slider control"];[self.window.contentView addSubview:self.slider];
 self.valueLabel=[NSTextField labelWithString:@"Value 20.00"];self.valueLabel.frame=NSMakeRect(24,70,300,24);[self.window.contentView addSubview:self.valueLabel];
 NSButton *close=[NSButton buttonWithTitle:@"Close diagnostic" target:NSApp action:@selector(terminate:)];close.frame=NSMakeRect(400,24,176,32);[self.window.contentView addSubview:close];
 __weak ProbeDelegate *weakSelf=self;
 self.monitor=[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskLeftMouseDown|NSEventMaskLeftMouseDragged|NSEventMaskLeftMouseUp handler:^NSEvent*(NSEvent *e){ProbeDelegate *s=weakSelf;if(e.window==s.window)Log(@"window-mouse",e,s.slider.doubleValue);return e;}];
 [self.window makeKeyAndOrderFront:nil];Log(@"ready",nil,self.slider.doubleValue);
 [NSTimer scheduledTimerWithTimeInterval:180 repeats:NO block:^(NSTimer *t){Log(@"deadline",nil,self.slider.doubleValue);[NSApp terminate:nil];}];
}
-(void)changed:(NSSlider*)sender{self.valueLabel.stringValue=[NSString stringWithFormat:@"Value %.2f",sender.doubleValue];Log(@"action",NSApp.currentEvent,sender.doubleValue);}
-(BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication*)sender{return YES;}
@end
int main(){@autoreleasepool{NSApplication *a=[NSApplication sharedApplication];a.activationPolicy=NSApplicationActivationPolicyRegular;ProbeDelegate *d=[ProbeDelegate new];a.delegate=d;[a run];}return 0;}
