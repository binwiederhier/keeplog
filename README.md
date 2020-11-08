keeplog
--
keeplog is a simple two-way synchronization tool to sync a local daily log with [Google Keep](https://keep.google.com). 
When run, keeplog parses the local file and synchronizes each entry to individual Keep notes. Updates within Keep are 
populated to the local file as well.

I mainly wrote it to learn Python and to support my workflow: I keep a local file in `~/LOG` with one entry 
per day, like this:

```
11/8/20 Sunday
--
Done
- Stuff

11/9/20 Monday
--
Todo
- More stuff
``` 

I love the simplicity of a single text file and I absolutely hate the Google Keep UI in the browser. My notes are very
extensive and often include code, so I like my text editor much more. But naturally, text files don't sync well, which 
is why keeplog exists -- so I can access and edit my notes from my phone if I have a brilliant idea and I'm not at 
the computer.

Installation
--
1. Create a config file `~/.keeplog/config` from [this template](config).
2. Run `./keeplog.py`

Copyright
--
Philipp C. Heckel, licensed under the Apache 2.0 License 