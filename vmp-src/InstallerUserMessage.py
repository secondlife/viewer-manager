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
import threading
import time
import Tkinter as tk
import ttk
#for hyperlinks
import webbrowser
from vmp_util import Application

#this is to support pyinstaller, which uses sys._MEIPASS to point to the location
#the bootloader unpacked the bundle to.  If the getattr returns false, we are in a 
#normal Python environment.
if getattr(sys, 'frozen', False):
    __file__ = sys._MEIPASS

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

    def __init__(self, text="", title="", width=500, height=200, wraplength = 400, icon_name = None, icon_path = None):
        tk.Tk.__init__(self)
        self.grid()
        self.title(title)
        self.choice = tk.BooleanVar()
        self.choice3 = tk.IntVar()
        self.config(background = 'black')
        # background="..." doesn't work on MacOS for radiobuttons or progress bars
        # http://tinyurl.com/tkmacbuttons
        ttk.Style().configure('Linden.TLabel', foreground=InstallerUserMessage.linden_green, background='black')
        ttk.Style().configure('Linden.TButton', foreground=InstallerUserMessage.linden_green, background='black')
        ttk.Style().configure("black.Horizontal.TProgressbar", foreground=InstallerUserMessage.linden_green, background='black')

        #This bit of configuration centers the window on the screen
        # The constants below are to adjust for typical overhead from the
        # frame borders.
        self.xp = (self.winfo_screenwidth()  / 2) - (width  / 2) - 8
        self.yp = (self.winfo_screenheight() / 2) - (height / 2) - 20
        self.geometry('{0}x{1}+{2}+{3}'.format(width, height, self.xp, self.yp))

        #find a few things
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.contents_dir = os.path.dirname(self.script_dir)
        self.icon_dir = os.path.abspath(os.path.join(self.contents_dir, 'Resources/vmp_icons'))
        if not os.path.exists(self.icon_dir):
            #not mac, so icons are not in ../Resources, but in a subdir of the app dir
            self.icon_dir = os.path.join(os.path.dirname(sys.executable), 'vmp_icons')

        #finds the icon and creates the widget
        self.find_icon(icon_path, icon_name)

        #defines what to do when window is closed
        self.protocol("WM_DELETE_WINDOW", self._delete_window)
        
        #callback id
        self.id = -1

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

    def find_icon(self, icon_path = None, icon_name = None):
        #we do this in each message, let's do it just once instead.
        if not icon_path:
            icon_path = self.icon_dir
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
            if x == heavy_column:
                self.columnconfigure(x, weight = 2)
            else:
                self.columnconfigure(x, weight=1)

        for y in range(row_count):
            if y == heavy_row:
                self.rowconfigure(y, weight = 2)
            else:
                self.rowconfigure(x, weight=1)

    def basic_message(self, message):
        #message: text to be displayed
        #icon_path: directory holding the icon, defaults to icons subdir of script dir
        #icon_name: filename of icon to be displayed
        self.choice.set(True)
        self.text_label = tk.Label(text = message)
        self.set_colors(self.text_label)
        self.set_colors(self.image_label)
        #pad, direction and weight are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 0, sticky = 'W')
        self.text_label.grid(row = 2, column = 0, sticky = 'W', padx =100)
        self.mainloop()

    def binary_choice_message(self, message, true = 'Yes', false = 'No'):
        #true: first option, returns True
        #false: second option, returns False
        #usage is kind of opaque and relies on this object persisting after the window destruction to pass back choice
        #usage:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   frame = frame.binary_choice_message( ... )
        #   (wait for user to click)
        #   value = frame.choice.get()

        self.text_label = tk.Label(text = message)
        #command registers the callback to the method named.  We want the frame to go away once clicked.
        #button 1 returns True/1, button 2 returns False/0
        self.button_one = ttk.Radiobutton(text = true, variable = self.choice, value = True, 
            command = self._delete_window, style = 'Linden.TButton')
        self.button_two = ttk.Radiobutton(text = false, variable = self.choice, value = False, 
            command = self._delete_window, style = 'Linden.TButton')
        self.set_colors(self.text_label)
        self.set_colors(self.image_label)
        #pads are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 1, columnspan = 2)
        self.text_label.grid(row = 2, column = 1, columnspan = 2, pady = 40)
        self.button_one.grid(row = 3, column = 1, padx = 30)
        self.button_two.grid(row = 3, column = 2, padx = 30)
        self.update()
        self.mainloop()
        
    def trinary_choice_message(self, message, one = 1, two = 2, three = 3):
        #one: first option, returns 1
        #two: second option, returns 2
        #three: third option, returns 3
        #usage is kind of opaque and relies on this object persisting after the window destruction to pass back choice
        #usage:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   frame = frame.binary_choice_message( ... )
        #   (wait for user to click)
        #   value = frame.choice.get()

        self.text_label = tk.Label(text = message)
        #command registers the callback to the method named.  We want the frame to go away once clicked.
        self.button_one = ttk.Radiobutton(text = one, variable = self.choice3, value = 1, 
            command = self._delete_window, style = 'Linden.TButton')
        self.button_two = ttk.Radiobutton(text = two, variable = self.choice3, value = 2, 
            command = self._delete_window, style = 'Linden.TButton')
        self.button_three = ttk.Radiobutton(text = three, variable = self.choice3, value = 3, 
            command = self._delete_window, style = 'Linden.TButton')
        self.set_colors(self.text_label)
        self.set_colors(self.image_label)
        #pads are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 0, columnspan = 3)
        self.text_label.grid(row = 2, column = 0, columnspan = 3, pady = 40)
        self.button_one.grid(row = 3, column = 0, padx = 10, pady = 10)
        self.button_two.grid(row = 3, column = 1, padx = 10, pady = 10)
        self.button_three.grid(row = 3, column = 2, padx = 10, pady = 10)
        self.update()
        self.mainloop() 

    def trinary_choice_link_message(self, message, url, one = 1, two = 2, three = 3):
        #url is hypertext for message
        #one: first option, returns 1
        #two: second option, returns 2
        #three: third option, returns 3
        #usage is kind of opaque and relies on this object persisting after the window destruction to pass back choice
        #usage:
        #   frame = InstallerUserMessage.InstallerUserMessage( ... )
        #   frame = frame.binary_choice_message( ... )
        #   (wait for user to click)
        #   value = frame.choice.get()
        #store url for callback, pick a failsafe default in case we get crap
        if url is not None and url != '':
            self.url = url
        else:
            self.url = 'http://www.secondlife.com'
        #stay on top even when browser is invoked
        self.attributes("-topmost", True)
        self.text_label = tk.Label(text = message)
        #bind the hyperlink text to the open action, "Button-1" is assigned by Tkinter
        self.text_label.bind("<Button-1>", self.link_callback)
        #command registers the callback to the method named.  We want the frame to go away once clicked.
        self.button_one = ttk.Radiobutton(text = one, variable = self.choice3, value = 1, 
            command = self._delete_window, style = 'Linden.TButton')
        self.button_two = ttk.Radiobutton(text = two, variable = self.choice3, value = 2, 
            command = self._delete_window, style = 'Linden.TButton')
        self.button_three = ttk.Radiobutton(text = three, variable = self.choice3, value = 3, 
            command = self._delete_window, style = 'Linden.TButton')
        self.set_colors(self.text_label)
        self.set_colors(self.image_label)
        #pads are all experimentally derived by retrying various values
        self.image_label.grid(row = 1, column = 0, columnspan = 3)
        self.text_label.grid(row = 2, column = 0, columnspan = 3, pady = 40)
        self.button_one.grid(row = 3, column = 0, padx = 10, pady = 10)
        self.button_two.grid(row = 3, column = 1, padx = 10, pady = 10)
        self.button_three.grid(row = 3, column = 2, padx = 10, pady = 10)      
        self.update()
        self.mainloop()
        
    def link_callback(self, event):
        webbrowser.open_new(self.url)   

    def progress_bar(self, message = None, size = 0, interval = 100, pb_queue = None):
        #Best effort attempt at a real progress bar
        #  This is what Tk calls "determinate mode" rather than "indeterminate mode"
        #size: denominator of percent complete
        #interval: frequency, in ms, of how often to poll the file for progress
        #pb_queue: queue object used to send updates to the bar
        self.text_label = tk.Label(text = message)
        self.set_colors(self.text_label)
        self.set_colors(self.image_label)
        self.image_label.grid(row = 1, column = 1, sticky = 'NSEW')
        self.text_label.grid(row = 2, column = 1, sticky = 'NSEW')
        self.progress = ttk.Progressbar(self, style = 'black.Horizontal.TProgressbar', orient="horizontal", length=100, mode="determinate")
        self.progress.grid(row = 3, column = 1, sticky = 'NSEW', pady = 25)
        self.value = 0
        self.progress["maximum"] = size
        self.auto_resize(row_count = 1, column_count = 3)
        self.queue = pb_queue
        self.check_scheduler()

    def check_scheduler(self):
        try:
            if self.value < self.progress["maximum"]:
                self.check_queue()            
                self.id = self.after(100, self.check_scheduler)
            else:
                #prevent a race condition between polling and the widget destruction
                self.after_cancel(self.id)
        except tk.TclError:
            #we're already dead, just die quietly
            pass

    def check_queue(self):
        while self.queue.qsize():
            try:
                msg = float(self.queue.get(0))
                #custom signal, time to tear down
                if msg == -1:
                    self.choice.set(True)
                    self.destroy()
                else:
                    self.progress.step(msg)
                    self.value = msg
            except Queue.Empty:
                #nothing to do
                return

class ThreadedClient(threading.Thread):
    #for test only, not part of the functional code
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.queue = queue

    def run(self):
        for x in range(1, 90, 10):
            time.sleep(1)
            print "run " + str(x)
            self.queue.put(10)
        #tkk progress bars wrap at exactly 100 percent, look full at 99%
        print "leftovers"
        self.queue.put(9)
        time.sleep(5)
        # -1 is a custom signal to the progress_bar to quit
        self.queue.put(-1)

if __name__ == "__main__":
    #When run as a script, just test the InstallUserMessage.  
    #To proceed with the test, close the first window, select on the second and fourth.  The third will close by itself.
    import sys
    import tempfile

    def set_and_check(frame, value):
        print "value: " + str(value)
        frame.progress.step(value)
        if frame.progress["value"] < frame.progress["maximum"]:
            print "In Progress"
        else:
            print "Over now"

    #basic message window test
    frame2 = InstallerUserMessage(text = "Something in the way she moves....", title = "Beatles Quotes for 100", icon_name="head-sl-logo.gif")
    frame2.basic_message(message = "...attracts me like no other.")
    print "Destroyed!"
    sys.stdout.flush()

    #binary choice test.  User destroys window when they select.
    frame3 = InstallerUserMessage(text = "Something in the way she knows....", title = "Beatles Quotes for 200", icon_name="head-sl-logo.gif")
    frame3.binary_choice_message(message = "And all I have to do is think of her.", 
        true = "Don't want to leave her now", false = 'You know I believe and how')
    print frame3.choice.get()
    sys.stdout.flush()
    
    #trinary choice test.  User destroys window when they select.
    frame3a = InstallerUserMessage(text = "Something in the way she knows....", title = "Beatles Quotes for 400", icon_name="head-sl-logo.gif")
    frame3a.trinary_choice_message(message = "And all I have to do is think of her.", 
        one = "Don't want to leave her now", two = 'You know I believe and how', three = 'John is Dead')
    print frame3a.choice3.get()
    sys.stdout.flush()
    
    #trinary link choice test. Click on message text to go to URL. User destroys window when they select.
    frame3b = InstallerUserMessage(text = "Come together....", title = "Beatles Quotes for 500", icon_name="head-sl-logo.gif")
    frame3b.trinary_choice_link_message(message = "Got to be good looking,\n'Cause he so hard to see", url = "http://www.ucla.edu", 
            one = "He bag production.", two = 'He got walrus gumboot.', three = 'He got Ono sideboard.')    
    print frame3b.choice3.get()
    sys.stdout.flush()    

    #progress bar
    queue = Queue.Queue()
    thread = ThreadedClient(queue)
    thread.start()
    print "thread started"

    frame4 = InstallerUserMessage(text = "Something in the way she knows....", title = "Beatles Quotes for 300", icon_name="head-sl-logo.gif")
    frame4.progress_bar(message = "You're asking me will my love grow", size = 100, pb_queue = queue)
    print "frame defined"
    frame4.mainloop()
