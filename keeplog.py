import gkeepapi
import re
from os.path import expanduser

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
        prevline = ""
        title = ""
        for line in f:
            if prevline != "":
                if line.strip() == "--": # and re.search('^\d+/\d+/\d+ ', prevline):
                    title = prevline.strip()
                elif title != "" and prevline.strip() != "--":
                    if title in log:
                        log[title] = log[title] + prevline
                    else:
                        log[title] = prevline
            prevline = line
        if title in log:
            log[title] = log[title] + prevline
        else:
            log[title] = prevline

    for k in log:
        print(k)
        print("--")
        print(log[k], end="")
    print(log)
    exit(1)

    # read keep
    # App password, see https://myaccount.google.com/apppasswords
    keep = gkeepapi.Keep()
    keep.login(username, password)

    note: gkeepapi.node.TopLevelNode
    for note in keep.all():

        label: gkeepapi.node.Label
        for label in note.labels:
            if label.name == "log":
                print(label)

            print(note.title)

if __name__ == '__main__':
    main()
