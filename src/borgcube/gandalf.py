import getpass
import locale
import os
import os.path
import shutil
import socket
import time
from collections import OrderedDict
from datetime import datetime
from urllib.parse import urlunsplit

from django.core.exceptions import ValidationError

import pytz

from ZODB.DB import DB

from borg.helpers import yes

try:
    import colorama

    colorama.init()
    from termcolor import colored
except ImportError:
    def colored(text, *args, **kwargs):
        return text


def conf():
    try:
        return os.environ['BORGCUBE_CONF']
    except KeyError:
        pass

    base = os.environ.get('XDG_CONFIG_HOME',
                          os.path.join(os.path.expanduser('~' + os.environ.get('USER', '')), '.config'))
    return os.path.join(base, 'borgcube', 'conf.py')


def datadir():
    base = os.environ.get('XDG_DATA_HOME',
                          os.path.join(os.path.expanduser('~' + os.environ.get('USER', '')), '.local', 'share'))
    return os.path.join(base, 'borgcube')


def ask_nicely(prompt, default=None, validators=()):
    def get():
        if default:
            return input(prompt + ' [' + default + '] → ').strip() or default
        else:
            return input(prompt + ' → ').strip()
    print()
    while True:
        value = get()
        try:
            for validator in validators:
                validator(value)
            return value
        except ValidationError as ve:
            for message in ve.messages:
                print(colored(message, attrs=['bold']))


def timezone(tz):
    if tz not in pytz.all_timezones:
        raise ValidationError('Invalid/unknown timezone ' + tz)


def executable(path):
    if path and not shutil.which(path):
        raise ValidationError('Not executable: ' + path)


def empty_dir(path):
    if os.path.exists(path):
        if not os.path.isdir(path):
            raise ValidationError('Not a directory: ' + path)
        if os.listdir(path):
            raise ValidationError('Directory not empty: ' + path)


def gandalf():
    config = OrderedDict()

    cf = conf()
    if os.path.isfile(cf):
        print('Configuration file', cf, 'already exists...')
        print('Wizard be gone now.')
        return 1

    print('Prompts are:')
    print('    what for [default] → your input here')
    print('Enter to use the default, ^C or ^D to abort at any time.')
    print()

    print('Preferred language code for anything, really')
    config['LANGUAGE_CODE'] = ask_nicely('Language code', locale.getlocale()[0])

    config['TIME_ZONE'] = ask_nicely('Time zone', time.tzname[0], validators=[timezone])

    print('Clients need to access this server through SSH, so I need to know a SSH login for this machine,')
    print('for the current user.')
    guessed_server_login = getpass.getuser() + '@' + socket.getfqdn()
    config['SERVER_LOGIN'] = ask_nicely('Login', guessed_server_login)

    print()
    # TODO link to yet-to-be-written section in manual about that
    print('If you are not using SSH forced commands, I need to know the path to the borgcube-proxy')
    print('binary. Note that not using forced commands means that clients can just regularly login')
    print('into the server!')
    print('Otherwise this can be left empty.')
    config['SERVER_PROXY_PATH'] = ask_nicely('borgcube-proxy path', shutil.which('borgcube-proxy'), validators=[executable])

    print()
    print('Next up: data storage')
    print('I\'ll need to store logs and my database somewhere. I\'ll be using the "logs"')
    print('subdirectory and a couple files named "DB.*" in there.')
    data_dir = ask_nicely('Data directory', datadir(), validators=[empty_dir])

    logs = config['SERVER_LOGS_DIR'] = os.path.join(data_dir, 'logs')
    db = os.path.join(data_dir, 'DB')
    config['DB_URI'] = urlunsplit(('file', '', db, '', ''))

    print('Logs directory:', logs)
    print('Database file: ', db)

    print()
    print('The web interface can be run by borgcubed or by a WSGI server. For the latter, just say "no".')
    web = ask_nicely('Web listen address', '127.0.0.1:8000')
    if web.lower() == 'no':
        web = None
    config['BUILTIN_WEB'] = web

    config['SECRET_KEY'] = os.urandom(32).hex()
    config['DEBUG'] = False

    print()
    print(colored('Configuration summary', attrs=['bold']))
    print(colored('---------------------', attrs=['bold']))
    print()
    print('Configuration file:   ', cf)
    print('Language, timezone:   ', config['LANGUAGE_CODE'] + ',', config['TIME_ZONE'])
    print('Server login:         ', config['SERVER_LOGIN'])
    print('Data directory:       ', data_dir)
    print('Builtin web interface:', config['BUILTIN_WEB'] or '(disabled/DIY)')
    print()
    msg = 'Write configuration? [Y/n] '
    if yes(msg, default=True, retry_msg=msg):
        print('Creating data directories ... ', end='')
        os.makedirs(logs, exist_ok=True)
        print('done.')

        # This is kinda unnecessary, because ZODB FS is create-on-first-use anyway, but if there
        # would be any unicorn errors during DB creation they'd pop up _now_, not later.
        print('Creating database ... ', end='')
        DB(db).close()
        print('done.')

        print('Writing configuration ... ', end='')
        with open(cf, 'w') as fd:
            print('# Generated by borgcube-gandalf on', datetime.now().isoformat(' '), file=fd)
            print('# User', getpass.getuser() + '@' + socket.getfqdn(), file=fd)
            print(file=fd)

            for key, value in config.items():
                print(key, '=', repr(value), file=fd)
        print('done.')


def _gandalf():
    try:
        return gandalf()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
