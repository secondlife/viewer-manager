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
#for hyperlinks
import webbrowser
from vmp_util import Application, SL_Logging, udir

# ****************************************************************************
#   status frame functionality
# ****************************************************************************
# When we're currently displaying a StatusMessage, this module global holds
# that instance so we can find it again. StatusMessage is just like
# InstallerUserMessage (see below) but with hooks to set/clear _status_frame.
_status_frame = None

def status_message(text):
    """
    Pass a string message. If this is the first status_message() call, this
    will pop up a new StatusMessage frame containing that text and immediately
    return. If there's already a StatusMessage frame displayed, it will
    instead update that frame with the new text.

    Pass None to close the StatusMessage frame.
    """
    global _status_frame
    # Log each status message we display to help diagnose VMP slow operation
    # -- since each log message gets a timestamp.
    log = SL_Logging.getLogger('status_message')
    if text is not None:
        # display new text
        log.info(text)
        if _status_frame is None:
            # StatusMessage constructor sets _status_frame
            frame = StatusMessage()
            frame.basic_message(text, wait=False)
        else:
            # there's an existing StatusMessage instance, just use that
            _status_frame.set_message(text)

    else:
        # text=None means: make the StatusMessage go away
        log.info("(close)")
        if _status_frame is not None:
            _status_frame.destroy()
            _status_frame = None

# ****************************************************************************
#   Convenience
# ****************************************************************************
def basic_message(text, **kwds):
    """
    basic_message(text) just pops up a message box which the user must clear.

    Any parameter overrides for the implicit InstallerUserMessage constructor
    must be passed as keyword arguments, e.g.:

    basic_message(text, title='This is a non-standard title')
    """
    # since by default InstallerUserMessage.basic_message() hangs around until
    # the user clears the message frame, we don't even need to save the instance
    InstallerUserMessage(**kwds).basic_message(text)

# ****************************************************************************
#   InstallerUserMessage class
# ****************************************************************************
class InstallerUserMessage(tk.Tk):
    #Goals for this class:
    #  Provide a uniform look and feel
    #  Provide an easy to use convenience class for other scripts
    #  Provide windows that automatically disappear when done (for differing notions of done)
    #  Provide a progress bar that isn't a glorified spinner, but based on download progress
    #Non-goals:
    #  No claim to threadsafety is made or warranted.  Your mileage may vary. 
    #     Please consult a doctor if you experience thread pain.

    #Linden standard green color, from Marketing
    linden_green = "#487A7B"

    def __init__(self, title=None, width=500, height=230,
                 icon_name = "head-sl-logo.gif", icon_path = None):
        # Before we even perform base-class initialization, suppress any
        # existing _status_frame. Deriving from tk.Tk (vs. tk.Frame) is great
        # when you know that any one of these might be the first visible
        # frame, but empirically, multiple concurrent instances of tk.Tk
        # subclasses confuse the communication between Python and Tkinter:
        # things end up in the wrong frame. Make them mutually exclusive by
        # destroying any existing _status_frame before constructing this tk.Tk
        # subclass.
        status_message(None)
        # Now initialize base class.
        tk.Tk.__init__(self)
        self.grid()
        self.title(title or Application.name())
        self.choice = tk.BooleanVar()
        self.choice3 = tk.IntVar()
        # Use of StringVar allows us to dynamically change the displayed text.
        self.message = tk.StringVar()
        # Use a Message widget for its automatic text reflow:
        # http://effbot.org/tkinterbook/message.htm
        # Initial width is arbitrary; we just need to suppress Message's
        # default behavior of trying to preserve the specified aspect ratio.
        self.text_label = tk.Message(textvariable=self.message, width=width)
        self.config(background = 'black')
        # background="..." doesn't work on MacOS for radiobuttons or progress bars
        # http://tinyurl.com/tkmacbuttons
        for style in 'Linden.TLabel', 'Linden.TButton', "black.Horizontal.TProgressbar":
            ttk.Style().configure(style, foreground=InstallerUserMessage.linden_green,
                                  background='black')

        #This bit of configuration centers the window on the screen
        #https://stackoverflow.com/q/3352918/5533635
        # The constants below are to adjust for typical overhead from the
        # frame borders.
        self.xp = (self.winfo_screenwidth()  / 2) - (width  / 2) - 8
        self.yp = (self.winfo_screenheight() / 2) - (height / 2) - 20
        self.geometry('{0}x{1}+{2}+{3}'.format(width, height, self.xp, self.yp))

        #find a few things
        if not icon_path:
            if platform.system() == "Darwin":
                # Unlike almost everything else we look for in Resources, the
                # vmp_icons are in the Resources directory for the embedded
                # launcher app rather than the sibling embedded viewer app. So
                # instead of calling Application.app_data_path(), just look
                # relative to __file__, which should be
                # launcher.app/Contents/MacOS/InstallerUserMessage.py
                # We want
                # launcher.app/Contents/Resources/vmp_icons
                icon_path = os.path.join(udir(), os.pardir, "Resources", "vmp_icons")
            else:
                #not mac, so icons are not in ../Resources, but in a subdir of the app dir
                icon_path = os.path.join(Application.install_path(), 'vmp_icons')
        if platform.system() == 'Windows':
            self.call('wm', 'iconbitmap', self._w, '-default',
                      os.path.join(icon_path, 'secondlife.ico'))

        #finds the icon and creates the widget
        self.find_icon(icon_path, icon_name)

        #defines what to do when window is closed
        self.protocol("WM_DELETE_WINDOW", self._delete_window)

        #callback id
        self.id = -1

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

    def set_message(self, message):
        self.message.set(message)
        self.set_colors(self.text_label)
        self.set_colors(self.image_label)
        self.update()

    def _delete_window(self):
        #capture and discard all destroy events before the choice is set
        if not ((self.choice == None) or (self.choice == "")):
            try:
                #initialized value.  If we have an outstanding callback, kill it before killing ourselves
                if self.id != -1:
                    self.after_cancel(self.id)
                self.destroy()
            except:
                #tk may try to destroy the same object twice
                pass

    def set_colors(self, widget):
        # #487A7B is "Linden Green"
        widget.config(foreground = InstallerUserMessage.linden_green)
        widget.config(background='black') 

    def find_icon(self, icon_path, icon_name):
        #we do this in each message, let's do it just once instead.
        icon_path = os.path.join(icon_path, icon_name)
        if os.path.exists(icon_path):
            icon = tk.PhotoImage(file=icon_path)
            self.image_label = tk.Label(image = icon)
            self.image_label.image = icon
        else:
            #default to text if image not available
            self.image_label = tk.Label(text = Application.name())

    def auto_resize(self, row_count = 0, column_count = 0, heavy_row = None, heavy_column = None):
        #auto resize window to fit all rows and columns
        #"heavy" gets extra weight
        for x in range(column_count):
            self.columnconfigure(x, weight=(2 if x == heavy_column else 1))

        for y in range(row_count):
            self.rowconfigure(y, weight=(2 if y == heavy_row else 1))

    # ---------------------------- basic_message -----------------------------
    def basic_message(self, message, wait=True):
        #message: text to be displayed
        #usage:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   frame.basic_message("message")
        #   # ^ waits for user to close message frame
        #usage for non-interactive status frame:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   frame.basic_message("initial status", wait=False)
        #   # ...
        #   frame.set_message("subsequent status")
        #   # ...
        #   frame.destroy()
        #icon_path: directory holding the icon, defaults to icons subdir of script dir
        #icon_name: filename of icon to be displayed
        self.choice.set(True)
        self.set_message(message)
        #pad, direction and weight are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 0, sticky = 'W')
        self.place_message(row = 2, column = 0, padx = 100)
        self.update()
        if wait:
            self.mainloop()

    # ------------------------ binary_choice_message -------------------------
    def binary_choice_message(self, message, true = 'Yes', false = 'No', wait=True):
        #true: first option, returns True
        #false: second option, returns False
        #usage:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   result = frame.binary_choice_message( ... )

        self.set_message(message)
        #command registers the callback to the method named.  We want the frame to go away once clicked.
        #button 1 returns True/1, button 2 returns False/0
        self.button_one = ttk.Radiobutton(text = true, variable = self.choice, value = True, 
            command = self._delete_window, style = 'Linden.TButton')
        self.button_two = ttk.Radiobutton(text = false, variable = self.choice, value = False, 
            command = self._delete_window, style = 'Linden.TButton')
        #pads are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 1, columnspan = 2)
        self.place_message(row = 2, column = 1, columnspan = 3, pady = 40)
        self.button_one.grid(row = 3, column = 2, padx = 30)
        self.button_two.grid(row = 3, column = 3, padx = 30)
        self.update()
        if wait:
            self.mainloop()
            return self.choice.get()

    # ------------------------ trinary_choice_message ------------------------
    def trinary_choice_message(self, message, one = 1, two = 2, three = 3, wait=True):
        #one: first option, returns 1
        #two: second option, returns 2
        #three: third option, returns 3
        #usage:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   result = frame.trinary_choice_message( ... )

        self.set_message(message)
        #command registers the callback to the method named.  We want the frame to go away once clicked.
        self.button = [ttk.Radiobutton(text = text, variable = self.choice3, value = v0+1,
                                       command = self._delete_window, style = 'Linden.TButton')
                       for v0, text in enumerate((one, two, three))]
        #pads are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 0, columnspan = 3)
        self.place_message(row = 2, column = 0, columnspan = 4, pady = 40)
        # We want column 0 to expand with the frame to reflow text
        # automatically: that's what place_message() does. So, don't put the
        # buttons into column 0 -- put them in 1, 2, 3 -- and make the message
        # widget span all 4 columns.
        for b in range(len(self.button)):
            self.button[b].grid(row = 3, column = b+1, padx = 10, pady = 10)
        self.update()
        if wait:
            self.mainloop()
            return self.choice3.get()

    # --------------------- trinary_choice_link_message ----------------------
    def trinary_choice_link_message(self, message, url, one = 1, two = 2, three = 3, wait=True):
        #url is hypertext for message
        #one: first option, returns 1
        #two: second option, returns 2
        #three: third option, returns 3
        #usage:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   result = frame.trinary_choice_link_message( ... )
        #store url for callback, pick a failsafe default in case we get crap
        self.url = url or 'http://www.secondlife.com'
        #stay on top even when browser is invoked
        self.attributes("-topmost", True)
        #bind the hyperlink text to the open action, "Button-1" is assigned by Tkinter
        self.text_label.bind("<Button-1>", self.link_callback)
        return self.trinary_choice_message(message, one=one, two=two, three=three, wait=wait)
        
    def link_callback(self, event):
        webbrowser.open_new(self.url)   

    def progress_bar(self, message, size):
        #Best effort attempt at a real progress bar
        #  This is what Tk calls "determinate mode" rather than "indeterminate mode"
        #size: denominator of percent complete
        self.set_message(message)
        self.image_label.grid(row = 1, column = 1, sticky = 'NSEW')
        self.place_message(row = 2, column = 1, sticky = 'NSEW')
        self.progress = ttk.Progressbar(self, style = 'black.Horizontal.TProgressbar', orient="horizontal", length=100, mode="determinate")
        self.progress.grid(row = 3, column = 1, sticky = 'NSEW', pady = 25)
        self.progress["maximum"] = size
        self.auto_resize(row_count = 1, column_count = 3)
        self.update()

    def step(self, value):
        self.progress.step(value)
        self.update()

# ****************************************************************************
#   StatusMessage
# ****************************************************************************
class StatusMessage(InstallerUserMessage):
    def __init__(self, *args, **kwds):
        # forward the call to base class constructor
        InstallerUserMessage.__init__(self, *args, **kwds)

        # set ourselves as canonical instance
        global _status_frame
        _status_frame = self

    def _delete_window(self):
        # canonical instance is going away
        global _status_frame
        _status_frame = None

        # forward the call to base class deletion handler
        InstallerUserMessage._delete_window(self)

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
