"""Main-thread macOS microphone authorization for the bundled desktop entry."""
from __future__ import annotations

import sys
import threading


def request_microphone_access(timeout: float = 120.0, api=None, observer=None) -> str:
    """Request audio capture access without opening or recording from a device."""
    def observe(event, **data):
        if observer is not None:
            observer(event, **data)

    if sys.platform != "darwin":
        return "unsupported"
    app_helper = None
    if api is None:
        import AVFoundation as api
        from AppKit import NSAlert, NSApplication, NSApplicationActivationPolicyRegular
        from Foundation import NSBundle
        from PyObjCTools import AppHelper as app_helper

        application = NSApplication.sharedApplication()
        application.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        application.finishLaunching()
        application.activateIgnoringOtherApps_(True)
        bundle = NSBundle.mainBundle()
        observe("context", bundle_identifier=str(bundle.bundleIdentifier() or ""),
                usage_description=bool(bundle.objectForInfoDictionaryKey_("NSMicrophoneUsageDescription")),
                main_thread=threading.current_thread() is threading.main_thread())

    media_type = api.AVMediaTypeAudio
    status = int(api.AVCaptureDevice.authorizationStatusForMediaType_(media_type))
    observe("status", value=status)
    values = {
        int(api.AVAuthorizationStatusAuthorized): "authorized",
        int(api.AVAuthorizationStatusDenied): "denied",
        int(api.AVAuthorizationStatusRestricted): "restricted",
    }
    if status != int(api.AVAuthorizationStatusNotDetermined):
        return values.get(status, "unknown")

    if app_helper is not None:
        observe("explanation_opened")
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Hebrew Live needs microphone access")
        alert.setInformativeText_("Audio stays on this Mac. Select Continue, then allow access in the macOS dialog.")
        alert.addButtonWithTitle_("Continue")
        alert.runModal()
        observe("explanation_closed")

    completed = threading.Event()
    granted: list[bool] = []

    def resolved(value):
        granted.append(bool(value))
        completed.set()
        if app_helper is not None:
            app_helper.callAfter(app_helper.stopEventLoop)

    observe("requested")
    api.AVCaptureDevice.requestAccessForMediaType_completionHandler_(media_type, resolved)
    if app_helper is None:
        completed.wait(timeout)
    else:
        timer = threading.Timer(timeout, lambda: app_helper.callAfter(app_helper.stopEventLoop))
        timer.daemon = True
        timer.start()
        try:
            app_helper.runConsoleEventLoop(installInterrupt=False, maxTimeout=0.1)
        finally:
            timer.cancel()
    if not completed.is_set():
        return "prompt_timeout"
    return "authorized" if granted and granted[0] else "denied"
