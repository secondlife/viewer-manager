#!/usr/bin/env python

"""\
$LicenseInfo:firstyear=2006&license=viewerlgpl$
Second Life Viewer Source Code
Copyright (C) 2006-2014, Linden Research, Inc.

This library is free software; you can redistribute it and/or
modify it under the terms of the GNU Lesser General Public
License as published by the Free Software Foundation;
version 2.1 of the License only.

This library is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public
License along with this library; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

Linden Research, Inc., 945 Battery Street, San Francisco, CA  94111  USA
$/LicenseInfo$
"""

"""
@file   InstallerUserMessage.py
@author coyot
@date   2016-05-16
"""

"""
This does everything the old updater/scripts/darwin/messageframe.py script did and some more bits.  
Pushed up the manager directory to be multiplatform.
"""

import os
import sys
import platform
import time
import traceback

# MAINT-8087: There is an unfortunate interaction between Pyinstaller and
# Tkinter. On Windows, Tkinter imports a helper module FixTk.py to set
# environment variables "TCL_LIBRARY", "TK_LIBRARY" and "TIX_LIBRARY" based on
# sys.prefix/tcl. But Pyinstaller unpacks all these modules into the running
# user's temp directory and sets sys.prefix accordingly. On modern Windows
# systems, the temp directory is found under c:\Users\<username> -- but when
# <username> includes non-ASCII characters, FixTk gets flummoxed and blows up.
# Fortunately, if "TCL_LIBRARY", "TK_LIBRARY" or "TIX_LIBRARY" are already set
# in the environment, it skips the check. It seems that Pyinstaller already
# sets "TCL_LIBRARY" and "TK_LIBRARY" but not "TIX_LIBRARY" -- having skipped
# lightly past the first two, it's the search for the last that actually blows
# up. We don't believe we ever try to engage tix; if we ever do, we hope that
# Pyinstaller will notice, build it in and set "TIX_LIBRARY" as well. For now
# it shouldn't (!) matter what is the value of "TIX_LIBRARY". Just make sure
# it HAS a value, to skip the fatal check in FixTk.py. Using setdefault()
# should ensure that if/when Pyinstaller actually sets it, we won't stomp it.
if platform.system() == 'Windows':
    os.environ.setdefault("TIX_LIBRARY", "")

import Tkinter as tk
import ttk
from tkSimpleDialog import Dialog
#for hyperlinks
import webbrowser
from util import Application, SL_Logging, udir

# ****************************************************************************
#   Tk root window
# ****************************************************************************
# We want the Tk root window to be available as needed -- but we don't want to
# initialize it at import time, only on demand. If we could define a "module
# property," we'd do that; since we can't, just use a function.
_root = None

def root():
    global _root
    if _root is None:
        try:
            # StatusMessage is our main window. Pop that up, even if there's no
            # message yet.
            _root = StatusMessage()
        except Exception:
            # We've seen cases in which Tkinter swallows exceptions. This
            # clause helps with debugging.
            traceback.print_exc()
            raise
    return _root

# ****************************************************************************
#   ModalRoot
# ****************************************************************************
class ModalRoot(tk.Tk):
    """
    This class attempts to unify the two major Tkinter use cases: as the
    framework for a UI application that calls mainloop(), and as 'side effect'
    UI for a console script that does not.

    From a console script, after creating or changing any widget, you must
    call update() to cause Tkinter to refresh the display in realtime. If you
    don't, either nothing is displayed, or the user sees a snapshot from some
    previous moment in time. (Empirically, update_idletasks() isn't enough.)

    But if you run mainloop(), you should NOT call update():
    http://effbot.org/tkinterbook/widget.htm#Tkinter.Widget.update-method
    'This method should be used with care, since it may lead to really nasty
    race conditions if called from the wrong place (from within an event
    callback, for example, or from a function that can in any way be called
    from an event callback, etc.).'

    This class presents a flush_display() method intended to properly update
    the display in either mode. Sprinkle calls to flush_display() after
    each change you want to make visible.
    """
    def __init__(self, *args, **kwds):
        tk.Tk.__init__(self, *args, **kwds)
        # set up flush_display() in console mode: nobody has called mainloop()
        self.flush_display = self.update

    def mainloop(self, *args, **kwds):
        flush_prev = self.flush_display
        # During any mainloop() call, flush_display() is a no-op
        self.flush_display = lambda: None
        try:
            return tk.Tk.mainloop(self, *args, **kwds)
        finally:
            self.flush_display = flush_prev

# ****************************************************************************
#   Methods common to main Tk window and auxiliary Dialogs
# ****************************************************************************
class Common(object):
    #Linden standard green color, from Marketing
    linden_green = "#487A7B"

    def __init__(self, parent, icon_name = "head-sl-logo.gif"):
        # Use of StringVar allows us to dynamically change the displayed text.
        self.message = tk.StringVar()
        # Use a Message widget for its automatic text reflow:
        # http://effbot.org/tkinterbook/message.htm
        # Initial width is arbitrary; we just need to suppress Message's
        # default behavior of trying to preserve the specified aspect ratio.
        self.text_label = tk.Message(master=parent, textvariable=self.message, width=150)
        self.set_colors(self.text_label)
        parent.config(background = 'black')
        # background="..." doesn't work on MacOS for radiobuttons or progress bars
        # http://tinyurl.com/tkmacbuttons
        for style in 'Linden.TLabel', 'Linden.TButton', "black.Horizontal.TProgressbar":
            ttk.Style().configure(style, foreground=Common.linden_green,
                                  background='black')

        #find a few things
        if platform.system() == "Darwin":
            # Unlike almost everything else we look for, our icons are in
            # our own updater/icons directory rather than the containing
            # viewer app. So instead of calling Application.app_data_path(),
            # just look relative to __file__.
            self.icon_path = os.path.join(udir(), "icons")
        else:
            #not mac, so icons are not in ../Resources, but in a subdir of the app dir
            self.icon_path = os.path.join(Application.install_path(), 'vmp_icons')

        if not os.path.exists(self.icon_path):
            # maybe we're in a developer directory?
            self.icon_path = os.path.join(udir(), "icons")

        #finds the icon and creates the widget
        #we do this in each message, let's do it just once instead.
        icon_path = os.path.join(self.icon_path, icon_name)
        if os.path.exists(icon_path):
            icon = tk.PhotoImage(file=icon_path)
            # empirically, we must *both* pass image= *and* set .image?!
            self.image_label = tk.Label(master=parent, image = icon)
            self.image_label.image = icon
        else:
            #default to text if image not available
            self.image_label = tk.Label(master=parent, text = Application.name())
        self.set_colors(self.image_label)

    def set_colors(self, widget):
        widget.config(foreground = Common.linden_green)
        widget.config(background='black') 

    def place_message(self, row, column, sticky='EW', **kwds):
        # Empirically, *all three* of sticky='EW', configuring the column
        # weight and resetting the Message width on <Configure> are necessary
        # for a self-adjusting Message with proper text flow.
        self.text_label.grid(row = row, column = column, sticky = sticky, **kwds)
        # necessary to make column stretch to fill the frame
        # https://mail.python.org/pipermail/python-list/2000-June/055758.html
        self.grid_columnconfigure(column, weight=1)
        # https://stackoverflow.com/a/8364895/5533635
        self.text_label.bind("<Configure>",
                             lambda event: self.text_label.config(width=event.width))

    # ---------------------- update the status message -----------------------
    def set_message(self, message):
        try:
            self.message.set(message)
            self.flush_display()
        except tk.TclError as err:
            pass

# ****************************************************************************
#   CustomDialog
# ****************************************************************************
class CustomDialog(Dialog, Common):
    def __init__(self, parent, message=""):
        # Dialog's constructor actually waits for user input, so set all
        # instance attributes BEFORE forwarding the call to base-class
        # constructor.
        self.__message = message
        # The same is necessarily true for any subclass with an __init__()
        # method of its own: set required attributes, THEN forward.
        Dialog.__init__(self, parent)

    def body(self, parent):
        # parent is actually a Frame constructed inside the parent Toplevel;
        # setting the Toplevel geometry doesn't cause the Frame to expand to
        # fill it without the following call:
        parent.pack(fill=tk.BOTH, expand=1)
        Common.__init__(self, parent)
        self.set_message(self.__message)
        self.geometry("470x200")
        # make sure Tk knows where parent is placed so can place us relative
        self.update_idletasks()

    def buttonbox(self):
        # Suppress the standard Dialog buttons.
        pass

    def flush_display(self):
        # Dialog uses wait_window() as its message loop. We need not (SHOULD
        # not) call update().
        pass

# ****************************************************************************
#   status_message(), StatusMessage
# ****************************************************************************
def status_message(text):
    """
    Pass a string message. If this is the first status_message() call, this
    will pop up a new StatusMessage window containing that text and
    immediately return. If there's already a StatusMessage frame displayed, it
    will instead update that window with the new text.

    Pass None to hide the StatusMessage window.
    """
    # Log each status message we display to help diagnose VMP slow operation
    # -- since each log message gets a timestamp.
    log = SL_Logging.getLogger('status_message')
    if text is not None:
        # display new text
        log.info(text)
        root().set_message(text)

    else:
        # text=None means: make the StatusMessage window go away
        log.info("(close)")
        root().hide()

class StatusMessage(ModalRoot, Common):
    """
    StatusMessage is our application's main window. It doesn't have any user
    input controls; it simply displays ongoing progress messages.
    """
    # -------------------- construction and configuration --------------------
    def __init__(self, title=None, width=500, height=230):
        # initialize base classes -- Tk uses old-style Python classes, which
        # don't support the super() idiom.
        ModalRoot.__init__(self)
        self.grid()
        Common.__init__(self, self)
        self.title(title or Application.name())

        #This bit of configuration centers the window on the screen
        #https://stackoverflow.com/q/3352918/5533635
        # The constants below are to adjust for typical overhead from the
        # frame borders.
        self.xp = (self.winfo_screenwidth()  / 2) - (width  / 2) - 8
        self.yp = (self.winfo_screenheight() / 2) - (height / 2) - 20
        self.geometry('{0}x{1}+{2}+{3}'.format(width, height, self.xp, self.yp))

        if platform.system() == 'Windows':
            self.call('wm', 'iconbitmap', self._w, '-default',
                      os.path.join(self.icon_path, 'secondlife.ico'))

        #defines what to do when window is closed
        self.protocol("WM_DELETE_WINDOW", self._delete_window)

        #pad, direction and weight are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 0, sticky = 'W')
        self.place_message(row = 2, column = 0, padx = 100)

        # Best effort attempt at a real progress bar
        #  This is what Tk calls "determinate mode" rather than "indeterminate mode"
        self.progress = ttk.Progressbar(self, style = 'black.Horizontal.TProgressbar',
                                        orient="horizontal", length=100, mode="determinate")
        self.progress.grid(row = 3, column = 0, sticky = 'NSEW', pady = 25, padx=25)
        # always create a progress bar, just hide it when not in use
        # https://stackoverflow.com/a/10268076
        self.progress.grid_remove()

    def _delete_window(self):
        try:
            self.destroy()
        except:
            #tk may try to destroy the same object twice
            pass

    # --------- display and step the (normally hidden) progress bar ----------
    def progress_bar(self, message, size):
        #size: denominator of percent complete
        self.set_message(message)
        # make hidden progress bar visible
        self.progress.grid()
        self.progress["maximum"] = size
        self.flush_display()

    def step(self, value, message=None):
        self.progress.step(value)
        if message:
            self.set_message(message)
        self.flush_display()

    def progress_done(self):
        self.progress.grid_remove()
        self.flush_display()

    # --------------------- hide our application window ----------------------
    def hide(self):
        # Although we want our own window to make way for the child viewer, we
        # don't want to destroy our window outright -- instead, leave an
        # invisible window. Its purpose is to provide the Taskbar/Dock icon,
        # allowing us to detect when the user clicks on said icon.
        ##self.withdraw()
        # It's actually important to use this incantation to hide the root
        # window: withdraw() leaves the Taskbar/Dock icon insensitive to
        # clicks, versus this alpha trick.
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError as err:
            pass
            # Updater's window was already terminated

# ****************************************************************************
#   basic_message(), BasicMessage
# ****************************************************************************
def basic_message(*args, **kwds):
    """
    basic_message(text) just pops up a message box which the user must clear.
    """
    try:
        BasicMessage(root(), *args, **kwds)
    except tk.TclError as err:
        pass

class BasicMessage(CustomDialog):
    def body(self, parent):
        CustomDialog.body(self, parent)
        self.image_label.grid(row = 1, column = 1, columnspan = 2)
        self.place_message(row = 2, column = 1, columnspan = 3, pady = 40)

# ****************************************************************************
# binary_choice_message(), BinaryChoiceMessage
# ****************************************************************************
def binary_choice_message(*args, **kwds):
    dlg = BinaryChoiceMessage(root(), *args, **kwds)
    return dlg.result.get()

class BinaryChoiceMessage(CustomDialog):
    def __init__(self, parent, message, true = 'Yes', false = 'No'):
        #true: first option, returns True
        #false: second option, returns False
        self.true   = true
        self.false  = false
        CustomDialog.__init__(self, parent, message)

    def body(self, parent):
        CustomDialog.body(self, parent)
        #command registers the callback to the method named. We want the frame
        #to go away once clicked. button 1 returns True, button 2 returns
        #False
        self.result = tk.BooleanVar()
        self.button_one = ttk.Radiobutton(master=parent, text = self.true, variable = self.result,
                                          value = True, command = self.cancel,
                                          style = 'Linden.TButton')
        self.button_two = ttk.Radiobutton(master=parent, text = self.false, variable = self.result,
                                          value = False, command = self.cancel,
                                          style = 'Linden.TButton')
        #pads are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 1, columnspan = 2)
        self.place_message(row = 2, column = 1, columnspan = 3, pady = 40)
        self.button_one.grid(row = 3, column = 2, padx = 30)
        self.button_two.grid(row = 3, column = 3, padx = 30)
        return self.button_one

# ****************************************************************************
#   trinary_choice_message(), TrinaryChoiceMessage
# ****************************************************************************
def trinary_choice_message(*args, **kwds):
    dlg = TrinaryChoiceMessage(root(), *args, **kwds)
    return dlg.result.get()

class TrinaryChoiceMessage(CustomDialog):
    def __init__(self, parent, message, url=None, one = 1, two = 2, three = 3):
        #url is hypertext for message
        #one: first option, returns 1
        #two: second option, returns 2
        #three: third option, returns 3
        self.url     = url
        self.choices = (one, two, three)
        CustomDialog.__init__(self, parent, message)

    def body(self, parent):
        CustomDialog.body(self, parent)
        #command registers the callback to the method named. We want the frame
        #to go away once clicked.
        self.result = tk.IntVar()
        self.button = [ttk.Radiobutton(master=parent, text = text, variable = self.result,
                                       value = v0+1, command = self.cancel,
                                       style = 'Linden.TButton')
                       for v0, text in enumerate(self.choices)]
        #pads are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 0, columnspan = 3)
        self.place_message(row = 2, column = 0, columnspan = 4, pady = 40)
        # We want column 0 to expand with the frame to reflow text
        # automatically: that's what place_message() does. So, don't put the
        # buttons into column 0 -- put them in 1, 2, 3 -- and make the message
        # widget span all 4 columns.
        for b, button in enumerate(self.button):
            button.grid(row = 3, column = b+1, padx = 10, pady = 10)

        # if URL was passed as action for clicking the message
        if self.url:
            #stay on top even when browser is invoked
            self.attributes("-topmost", True)
            #bind the hyperlink text to the open action, "Button-1" is assigned by Tkinter
            self.text_label.bind("<Button-1>", lambda event: webbrowser.open_new(self.url))

        return self.button[0]

# ****************************************************************************
#   Testing
# ****************************************************************************
if __name__ == "__main__":
    #When run as a script, just test the InstallUserMessage.  
    #To proceed with the test, close the first window, select on the second and fourth.  The third will close by itself.

    #basic message window test
    frame2 = InstallerUserMessage(title = "Beatles Quotes for 100")
    frame2.basic_message(message = "...attracts me like no other.")
    print "Destroyed!"
    sys.stdout.flush()

    #binary choice test.  User destroys window when they select.
    frame3 = InstallerUserMessage(title = "Beatles Quotes for 200")
    frame3.binary_choice_message(message = "And all I have to do is think of her.", 
        true = "Don't want to leave her now", false = 'You know I believe and how')
    print frame3.choice.get()
    sys.stdout.flush()
    
    #trinary choice test.  User destroys window when they select.
    frame3a = InstallerUserMessage(title = "Beatles Quotes for 400")
    frame3a.trinary_choice_message(message = "And all I have to do is think of her.", 
        one = "Don't want to leave her now", two = 'You know I believe and how', three = 'John is Dead')
    print frame3a.choice3.get()
    sys.stdout.flush()
    
    #trinary link choice test. Click on message text to go to URL. User destroys window when they select.
    frame3b = InstallerUserMessage(title = "Beatles Quotes for 500")
    frame3b.trinary_choice_link_message(message = "Got to be good looking,\n'Cause he so hard to see", url = "http://www.ucla.edu", 
            one = "He bag production.", two = 'He got walrus gumboot.', three = 'He got Ono sideboard.')    
    print frame3b.choice3.get()
    sys.stdout.flush()    

    #progress bar
    frame4 = InstallerUserMessage(title = "Beatles Quotes for 300")
    frame4.progress_bar(message = "You're asking me will my love grow", size = 100)
    print "frame defined"
    for x in range(1, 90, 10):
        time.sleep(1)
        print "run " + str(x)
        frame4.step(10)
    #tkk progress bars wrap at exactly 100 percent, look full at 99%
    print "leftovers"
    frame4.step(9)
    time.sleep(5)
    frame4.destroy()
