Viewer Management Process
=========================

This is the master process that is launched for the Second Life
Viewer (https://bitbucket.org/lindenlab/viewer-release). It manages
updates and will soon manage crash data collection and reporting.

To build it, you'll need to have the python 'nose' package installed.
You need the 'nose' package (a python testing framework) installed:

`pip install nose`

and set the `nosetests` environment to the location of the `nosetests`
executable. If you installed nose such that it is in your path, this
will work:

```
export nosetests=nosetests;
autobuild build
autobuild package
```

If you want to support both 32 and 64 bit Windows, you'll need to
build this with a 32 bit Windows python and use the resulting .exe for
both. 
