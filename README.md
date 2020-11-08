keeplog
--
**keeplog** is a simple two-way synchronization tool to sync a local daily log with [Google Keep](https://keep.google.com). 
When run, keeplog parses the local file and synchronizes each entry to individual Keep notes. Updates within Keep are 
populated to the local file as well.

_keeplog is work-in-progress, so use with caution!_

I mainly wrote it to learn Python and to support my workflow: I keep a local file in `~/LOG` with one entry 
per day, like this:

```
11/5/20 Friday
--
Todo
- More stuff

11/8/20 Sunday
--
Done
- Stuff
``` 

I love the simplicity of a single text file and I absolutely hate the Google Keep UI in the browser. My notes are very
extensive and often include code, so I like my text editor much more. But naturally, text files don't sync well, which 
is why keeplog exists -- so I can access and edit my notes from my phone if I have a brilliant idea and I'm not at 
the computer.

Installation
--
1. Create a [Google App Password](https://myaccount.google.com/apppasswords) for keeplog
2. Create a config file `~/.keeplog/config` from [this template](config). Be sure to edit at least 
   `user=`, `pass=` and `file=`.
3. Install dependencies via `pip3 install -r requirements.txt`.
4. Run `./keeplog.py`, you'll see something like this:

```
2020-11-08 13:33:50,038 [INFO] Logging in with token
2020-11-08 13:33:59,221 [INFO] Successfully logged in
2020-11-08 13:33:59,221 [INFO] Comparing remote and local
2020-11-08 13:33:59,221 [INFO] Reading local notes
2020-11-08 13:33:59,230 [INFO] Reading remote notes
2020-11-08 13:33:59,234 [INFO] - Updating locally: 11/5/20 Friday
2020-11-08 13:33:59,234 [INFO] - Updating remotely: 11/8/20 Sunday
2020-11-08 13:33:59,616 [INFO] Writing local notes
```

Copyright
--
Philipp C. Heckel, licensed under the Apache 2.0 License   
Thanks very much to [kiwiz](https://github.com/kiwiz) for his excellent [gkeepapi](https://github.com/kiwiz/gkeepapi). 