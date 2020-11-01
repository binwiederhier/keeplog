import gkeepapi
import re
from datetime import datetime
from os.path import expanduser

class Entry:
    def __init__(self, title, text, date):
        self.title = title
        self.text = text
        self.date = date

def main():
    # read config
    config = expanduser("~/.config/keeplog.conf")
    try:
        with open(config) as cfg:
            for line in cfg:
                match = re.search("^([^=]+)=(.+)", line)
                if match:
                    if match.group(1) == "user":
                        username = match.group(2)
                    elif match.group(1) == "pass":
                        password = match.group(2)
                    elif match.group(1) == "file":
                        file = match.group(2)
    except:
        print("Cannot read config file " + config)

    if not username or not password or not file:
        print("Invalid config file, need at least 'user=', 'pass=' and 'log='.")

    # parse log
    log = {}
    with open(expanduser(file)) as f:
        for line in f:
            match = re.search('^(\d+)/(\d+)/(\d+) ', line)
            if match:
                title = line.strip()
                date = datetime(year=2000+int(match.group(3)), month=int(match.group(1)), day=int(match.group(2)))
                log[title] = Entry(title, "", date)
            elif line.strip() != "--" and title in log:
                log[title].text = log[title].text + line

  #  for k in log:
  #      print(log[k].title)
  #      print("--")
  #      print(log[k].text, end="")

    #exit(1)

    # read keep
    # App password, see https://myaccount.google.com/apppasswords
    keep = gkeepapi.Keep()
    keep.login(username, password)

    notes = {}
    label = keep.findLabel('log')

    note: gkeepapi.node.TopLevelNode
    for note in keep.find(labels=[label]):
        if not re.search('^\d+/\d+/\d+ ', note.title):
            print(f"{note.title} - Skipping, title mismatch")
            continue
        notes[note.title] = note

   # for title in notes.keys():
   #     note = notes[title]
   #     print(note.title)
   #     print("-- ")
   #     print(note.text, end="")

    #exit(1)

    for entry in log.values():
        if not entry.title in notes:
            print(f"{entry.title} - Creating remotely")
            note = keep.createNote(entry.title, entry.text)
            note.timestamps.created = entry.date
            note.timestamps.edited = entry.date
            note.labels.add(label)
        elif notes[entry.title].text != entry.text:
            print(f"{entry.title} - Updating remotely")
            notes[title].text = entry.text
            notes[title].timestamps.created = entry.date
            notes[title].timestamps.edited = entry.date
        else:
            print(f"{entry.title} - Up to date")

    keep.sync()

if __name__ == '__main__':
    main()
