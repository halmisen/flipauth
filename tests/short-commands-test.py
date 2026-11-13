#!/usr/bin/env python3
"""Exercise short commands, wrappers and full switch jobs with real fake-CLI PIDs."""

import importlib.util
import json
import os
import pty
import re
import select
import termios
import threading
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("directory_tests", Path(__file__).with_name("directory-accounts-test.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
sys.path.insert(0, str(base.REPO / 'lib'))
import directory_accounts as accounts
import session_switch as lifecycle

HELPERS = r'''
import contextlib, fcntl, json, os
from pathlib import Path
path = Path(os.environ['FX_STATE'])
@contextlib.contextmanager
def state():
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text())
        yield data
        path.write_text(json.dumps(data))
def alive(pid):
    try: return Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[0] != 'Z'
    except FileNotFoundError: return False
'''

CLI = r'''#!/usr/bin/env python3
import json, os, signal, sys, time
from pathlib import Path
from fixture_helpers import state, alive
service = Path(sys.argv[0]).name.split('-')[0]
directory = Path(os.environ['CODEX_HOME' if service == 'codex' else 'CLAUDE_CONFIG_DIR'])
args = sys.argv[1:]
if args[:3] == ['app-server', 'daemon', 'start']:
    sys.exit('forbidden: FlipAuth must let the interactive CLI auto-start its daemon')
if args[:1] == ['app-server']:
    role='updater' if args[1:3] == ['daemon','pid-update-loop'] else 'server'
    with state() as data:
        data.setdefault('daemons',{})[str(os.getpid())]={'home':str(directory),'role':role}
        data['events'].append(['daemon-started',role,str(directory),os.getpid()])
    def stop_daemon(sig,frame):
        with state() as data: data['events'].append(['daemon-stopped',role,str(directory),os.getpid()])
        sys.exit(0)
    signal.signal(signal.SIGTERM,stop_daemon)
    (directory/('daemon-ready-'+str(os.getpid()))).touch()
    while True: time.sleep(.02)
if service == 'codex' and args[:1] != ['login'] and '--no-daemon' not in args:
    with state() as data:
        exists=any(row['home']==str(directory) and row['role']=='server' and alive(int(pid))
                   for pid,row in data.get('daemons',{}).items())
    if not exists:
        import subprocess
        daemon_dir = directory / 'app-server-daemon'
        daemon_dir.mkdir(exist_ok=True)
        for filename, command in [('daemon.pid', ['app-server', '--managed-daemon', '--listen', 'unix://']),
                                  ('daemon-updater.pid', ['app-server', 'daemon', 'pid-update-loop'])]:
            child = subprocess.Popen([sys.argv[0], *command], env=os.environ,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
            ticks = int(Path('/proc/'+str(child.pid)+'/stat').read_text().rsplit(')',1)[1].split()[19])
            (daemon_dir / filename).write_text(json.dumps({'pid':child.pid, 'processIdentity':{
                'startTicks':ticks, 'bootId':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}}))
            deadline=time.monotonic()+3
            while not (directory/('daemon-ready-'+str(child.pid))).exists():
                if child.poll() is not None or time.monotonic()>deadline: sys.exit(40)
                time.sleep(.01)
record = {'home':str(directory),'args':args,'pid':os.getpid(),'cwd':os.getcwd()}
(directory/'called.json').write_text(json.dumps(record))
with state() as data: data['events'].append(['invoked',str(directory),os.getpid(),os.getcwd()])
if args[:1] == ['login'] or args[:2] == ['auth','login']:
    (directory/('auth.json' if service == 'codex' else '.credentials.json')).write_text('{}')
    sys.exit(0)
if '--once' in args or '--version' in args:
    print(json.dumps(record)); sys.exit(0)
pane = os.environ['FX_PANE']
with state() as data:
    data['panes'][pane]['pid'] = os.getpid()
    data['panes'][pane]['home'] = str(directory)
    data['panes'][pane]['status'] = 'working'
    data['events'].append(['started',pane,str(directory)])
# Like the native TUIs: raw mode plus alternate screen, mouse, focus and paste reporting.
import select, termios, tty
MODES = b'\x1b[?1049h\x1b[?1000h\x1b[?1003h\x1b[?1006h\x1b[?1004h\x1b[?2004h'
saved = termios.tcgetattr(0)
tty.setraw(0)
os.write(1, MODES)
def restore():
    os.write(1, MODES.replace(b'h', b'l'))
    termios.tcsetattr(0, termios.TCSAFLUSH, saved)
def finish(how):
    restore()
    with state() as data: data['events'].append(['exited',pane,how])
    sys.exit(0)
if service == 'claude':
    # Native Claude restores its terminal on SIGTERM; native Codex installs no handler.
    signal.signal(signal.SIGTERM, lambda sig, frame: finish('sigterm'))
def keys():
    if not select.select([0],[],[],.02)[0]: return
    for byte in os.read(0, 64):
        if byte not in (3, 27): continue
        with state() as data:
            row = data['panes'][pane]
            if data.get('stubborn') or row.get('stubborn'): continue
            if byte == 27:
                data['events'].append(['esc',pane,row['status']])
                if row['status'] == 'task_modal':
                    row['status'] = 'working'
                elif row['status'] == 'working':
                    row['status'] = 'idle'
                continue
            data['events'].append(['ctrl+c',pane,row['status']])
            if row['status'] == 'working':
                row['status'] = 'task_modal'; continue
            if row['status'] == 'task_modal':
                continue
        finish('ctrl+c')
(directory/('ready-'+pane)).touch()
if os.environ.get('FX_SWITCH_ON_START') and directory.name == '.codex':
    import subprocess
    import pty
    master,slave=pty.openpty()
    result=subprocess.run([os.environ['FX_FLIPAUTH'],'cod','secondary'],stdin=slave,capture_output=True,text=True)
    os.close(master); os.close(slave)
    (directory/'nested-result').write_text(json.dumps({'rc':result.returncode,'error':result.stderr}))
while True: keys()
'''

PS = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
from fixture_helpers import state, alive
with state() as data:
    for pane,row in data['panes'].items():
        pid=row.get('pid')
        present = pid and Path('/proc/'+str(pid)).exists()
        if pid and (alive(pid) or (data.get('include_zombies') and present)):
            prefix = str(pid)+' 1 '
            if '-eo' in sys.argv: prefix += 'pts/9 '
            prefix += row['service']+' '
            print(prefix+row['service']+' --fixture')
    for pid in data.get('daemons',{}):
        if alive(int(pid)): print(pid+' 1 codex daemon')
'''




HERDR = r'''#!/usr/bin/env python3
import json, sys
from fixture_helpers import state, alive
args = sys.argv[1:]
if args[:1] == ['--session']:
    if args[1] != 'fx': sys.exit(3)
    args = args[2:]
with state() as data:
    panes = {name: row for name, row in data['panes'].items() if row.get('managed')}
    if args == ['session', 'list', '--json']:
        print(json.dumps({'sessions': [{'name': 'fx', 'running': True}]}))
    elif args == ['api', 'snapshot']:
        print(json.dumps({'result': {'snapshot': {'panes': [
            {'pane_id': p, 'agent_status': 'working' if panes[p].get('status') in {'working', 'task_modal'} else 'idle'}
            for p in panes
        ]}}}))
    elif args[:3] == ['pane', 'process-info', '--pane'] and args[3] in panes:
        row = panes[args[3]]
        live = row.get('pid') and alive(row['pid'])
        rows = [{'pid': row['pid'], 'name': row['service']}] if live else [{'pid': 1, 'name': 'bash'}]
        print(json.dumps({'result': {'process_info': {'pane_id': args[3], 'shell_pid': 1,
                                                       'foreground_processes': rows}}}))
    elif args[:2] == ['agent', 'send-keys'] and args[2] in panes:
        row = panes[args[2]]
        # Like Herdr: agent input is rejected once the agent no longer controls the pane.
        if not (row.get('pid') and alive(row['pid'])): sys.exit(4)
        row.setdefault('keys', []).extend(args[3:])
        data['events'].append(['send-keys', args[2], *args[3:]])
    else:
        sys.exit(2)
'''

KEYS = {'ctrl+c': b'\x03', 'esc': b'\x1b'}
MODE = re.compile(rb'\x1b\[\?([0-9]+)([hl])')


class ShortCommands(unittest.TestCase):
    setUpBase = base.Accounts.setUp
    call = base.Accounts.call
    create = base.Accounts.create
    record = base.Accounts.record
    wait_file = base.Accounts.wait_file

    def setUp(self):
        self.setUpBase()
        self.statefile = self.root / 'fixture.json'
        self.statefile.write_text(json.dumps({'panes':{},'events':[]}))
        self.env.update(FX_STATE=str(self.statefile), FLIPAUTH_PS_BIN=str(self.bin/'ps'),
                        FLIPAUTH_HERDR_BIN=str(self.bin/'herdr'), FLIPAUTH_SWITCH_STOP_TIMEOUT='2')
        (self.bin/'fixture_helpers.py').write_text(HELPERS)
        for filename, text in [('ps',PS),('herdr',HERDR),('codex-official',CLI),('claude-official',CLI)]:
            path=self.bin/filename; path.write_text(text); path.chmod(0o700)
        self.addCleanup(self.cleanup_processes)
        # A tiny terminal host: owns each pane's PTY master like Herdr does.
        self.masters, self.output, self.running = {}, {}, True
        self.pump = threading.Thread(target=self.pump_terminals, daemon=True)
        self.pump.start()
        self.addCleanup(self.stop_pump)

    def stop_pump(self):
        self.running = False
        self.pump.join(timeout=3)
        for master in self.masters.values(): os.close(master)

    def locked_state(self):
        import contextlib, fcntl
        @contextlib.contextmanager
        def locked():
            with self.statefile.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                text = self.statefile.read_text()
                data = json.loads(text)
                yield data
                if json.dumps(data) != json.dumps(json.loads(text)):
                    self.statefile.write_text(json.dumps(data))
        return locked()

    def pump_terminals(self):
        while self.running:
            for pane, master in list(self.masters.items()):
                while select.select([master], [], [], 0)[0]:
                    try: data = os.read(master, 65536)
                    except OSError: break
                    if not data: break
                    self.output[pane] += data
                with self.locked_state() as data:
                    queued = data['panes'][pane].pop('keys', [])
                for key in queued:
                    try: os.write(master, KEYS[key])
                    except OSError: pass
            time.sleep(.01)

    def terminal(self, pane):
        """Return (modes ever enabled, modes still enabled, cooked+echo restored)."""
        time.sleep(.1)
        states, seen = {}, set()
        for mode, value in MODE.findall(bytes(self.output[pane])):
            states[mode.decode()] = value == b'h'
            if value == b'h': seen.add(mode.decode())
        flags = termios.tcgetattr(self.masters[pane])[3]
        return seen, {m for m, on in states.items() if on}, bool(flags & termios.ICANON and flags & termios.ECHO)

    def assert_terminal_restored(self, pane):
        seen, left, cooked = self.terminal(pane)
        # Positive control: the fixture really enabled the modes it must clear.
        self.assertTrue({'1049', '1003', '1006', '2004', '1004'} <= seen, seen)
        self.assertEqual(left, set(), 'terminal modes left enabled in old pane '+pane)
        self.assertTrue(cooked, 'old pane left in raw mode without echo')

    def state(self, **values):
        # Tests only update metadata before submitting workers, never during mutation.
        with self.locked_state() as data:
            data.update(values)
        return data

    def cleanup_processes(self):
        data=json.loads(self.statefile.read_text())
        for pid in data.get('daemons', {}):
            try: os.kill(int(pid),signal.SIGTERM)
            except ProcessLookupError: pass
        for row in data['panes'].values():
            pid=row.get('pid')
            if pid:
                try: os.kill(pid,signal.SIGTERM)
                except ProcessLookupError: pass
        for process in getattr(self,'originals',[]):
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            live=any(lifecycle.identity(int(pid)) is not None for pid in data.get('daemons',{}))
            for row in data['panes'].values():
                try:
                    fields=Path('/proc/'+str(row.get('pid'))+'/stat').read_text().rsplit(')',1)[1].split()
                    live=live or fields[0]!='Z'
                except FileNotFoundError: pass
            if not live: break
            time.sleep(.02)

    def short(self, service, *args, ok=True, terminal=True, **kwargs):
        values=list(map(str,args))
        is_switch = values and values[0] not in {'status','list','new','--help'} and values[1:2] != ['login']
        if is_switch and '--once' not in values: values += ['--','--once']
        master,slave=pty.openpty()
        try:
            result=subprocess.run([str(self.program),service,*values], env=self.env,
                                  stdin=slave if terminal else subprocess.DEVNULL,
                                  capture_output=True,text=True,timeout=12,**kwargs)
        finally:
            os.close(master); os.close(slave)
        self.assertEqual(result.returncode,0,result.stderr) if ok else self.assertNotEqual(result.returncode,0)
        self.assertNotIn('Traceback',result.stderr)
        return result

    def setup_accounts(self, service='codex'):
        first=self.home/('.'+service); first.mkdir(mode=0o700)
        self.call(service,'add','primary',first,'--default')
        second=self.create(service,'secondary')
        credential='auth.json' if service=='codex' else '.credentials.json'
        for directory in (first,second): (directory/credential).write_text('{}')
        return first,second

    def start(self, pane, service, directory, managed=True, extra_env=None):
        cwd=self.root/('project '+pane); cwd.mkdir()
        with self.locked_state() as data:
            data['panes'][pane]={'service':service,'cwd':str(cwd),'status':'working','managed':managed}
        env={**self.env,'FX_PANE':pane, 'CODEX_HOME' if service=='codex' else 'CLAUDE_CONFIG_DIR':str(directory)}
        env.update(extra_env or {})
        master,slave=pty.openpty()
        process=subprocess.Popen([self.env['FLIPAUTH_'+service.upper()+'_BIN']],env=env,cwd=cwd,
                                 stdin=slave,stdout=slave,stderr=subprocess.DEVNULL,start_new_session=True)
        os.close(slave)
        self.output[pane]=bytearray(); self.masters[pane]=master
        self.originals=getattr(self,'originals',[])+[process]
        self.wait_file(directory/('ready-'+pane),process)
        return process

    def receipt(self, service='codex'):
        paths=list((self.root/'registry/switches').glob(service+'-*.json'))
        self.assertTrue(paths)
        return json.loads(max(paths,key=lambda p:p.stat().st_mtime_ns).read_text())

    def test_login_creates_home_once_and_imports_no_snapshots(self):
        self.short('cod','secondary','login','--','--device-auth')
        directory=self.home/'.codex-secondary'
        self.assertTrue((directory/'auth.json').exists())
        self.assertEqual(self.record(directory)['args'],['login','--device-auth'])
        self.short('cod','secondary','login')
        self.short('cc','secondary','login')
        self.assertTrue((self.home/'.claude-secondary/.credentials.json').exists())
        self.assertFalse(list(self.home.rglob('.active-profile')))
        self.short('codex','new','third')
        self.assertTrue((self.home/'.codex-third').is_dir())

    def test_status_distinguishes_login_selection_and_historical_switch(self):
        first, second = self.setup_accounts()
        jobs = self.root/'registry/switches'
        jobs.mkdir()
        (jobs/'codex-old.json').write_text(json.dumps({
            'state':'failed', 'target':'secondary', 'error':'old failure'}))
        self.short('cod', 'secondary', 'login')
        result = self.short('cod', 'status').stdout
        self.assertIn('selected: primary', result)
        self.assertIn('directory: '+str(first), result)
        self.assertIn('local login file: present (identity unverified)', result)
        self.assertIn('launch selected: flipauth codex account current --', result)
        self.assertIn('Login does not update the last switch receipt.', result)
        self.assertIn('last switch: failed -> secondary', result)
        self.assertIn('Plain codex follows selection only after bind-current is installed on PATH.', result)
        self.assertEqual(json.loads((jobs/'codex-old.json').read_text())['error'], 'old failure')
        (first/'auth.json').unlink()
        self.assertIn('local login file: missing', self.short('cod', 'status').stdout)

    def test_plain_wrapper_follows_both_switch_directions(self):
        first,second=self.setup_accounts()
        wrappers=self.root/'wrappers'; wrappers.mkdir()
        wrapper=wrappers/'codex'
        self.call('codex','bind-current',wrapper)
        for label,directory in [('secondary',second),('primary',first)]:
            self.short('cod',label,'--','--once')
            result=subprocess.run([str(wrapper),'--once','a b',"'",'$HOME'],env=self.env,
                                  capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            record=json.loads(result.stdout)
            self.assertEqual(record['home'],str(directory))
            self.assertEqual(record['args'],['--once','a b',"'",'$HOME'])
        self.assertFalse((self.home/'tripwire').exists())

    def test_busy_clis_and_daemon_stop_before_one_new_cli_and_other_service_survives(self):
        first,second=self.setup_accounts()
        claude=self.create('claude','other')
        a=self.start('a','codex',first); b=self.start('b','codex',first)
        other=self.start('c','claude',claude)
        cwd=self.root/'new terminal cwd'; cwd.mkdir()
        result=self.short('cod','secondary',cwd=cwd)
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'exec-admitted',receipt)
        self.assertEqual(a.wait(timeout=3),0); self.assertEqual(b.wait(timeout=3),0)
        self.assertIsNone(other.poll())
        for pane in ('a','b'): self.assert_terminal_restored(pane)
        self.assertEqual({row['exit'] for row in receipt['stopped_cli']},{'ctrl+c'})
        self.assertEqual({row['pid'] for row in receipt['stopped_cli']},{a.pid,b.pid})
        record=self.record(second)
        self.assertEqual(record['pid'],receipt['pid'])
        self.assertEqual(record['cwd'],str(cwd))
        self.assertEqual(record['args'],['--once'])
        events=self.state()['events']
        new_index=next(i for i,e in enumerate(events) if e[:2]==['invoked',str(second)])
        old_stops=[i for i,e in enumerate(events) if e[0] in {'exited','daemon-stopped'}]
        self.assertTrue(old_stops and max(old_stops)<new_index)
        roles=[e[1] for e in events if e[0]=='daemon-stopped']
        self.assertEqual(roles,['updater','server'])
        self.assertFalse(any(e[0]=='run' for e in events))
        self.assertEqual(len([e for e in events if e[:2]==['invoked',str(second)]]),1)
        self.assertIn('selected: secondary',self.short('cod','status').stdout)

    def test_named_launcher_for_the_running_account_joins_without_stopping_anything(self):
        first, _ = self.setup_accounts()
        original = self.start('a', 'codex', first)
        launcher = self.bin / 'codex-primary'
        self.call('codex', 'bind', 'primary', launcher, '--switch')
        master,slave=pty.openpty()
        try:
            result=subprocess.run([str(launcher),'--once'],env=self.env,stdin=slave,
                                  capture_output=True,text=True,timeout=12)
        finally:
            os.close(master); os.close(slave)
        self.assertEqual(result.returncode,0,result.stderr)
        receipt=self.receipt()
        self.assertEqual((receipt['state'],receipt['mode']),('exec-admitted','same-account'),receipt)
        self.assertIsNone(original.poll())
        self.assertNotEqual(self.record(first)['pid'],original.pid)
        events=self.state()['events']
        self.assertFalse(any(e[0] in {'send-keys','exited','daemon-stopped'} for e in events))
        self.assertEqual(self.record(first)['args'],['--once'])

    def test_account_change_closes_every_pane_in_parallel_and_all_daemons(self):
        first,second=self.setup_accounts()
        panes=[self.start(name,'codex',first) for name in ('a','b','c')]
        target_pane=self.start('d','codex',second)
        started=time.monotonic()
        self.short('cod','primary')
        elapsed=time.monotonic()-started
        for process in [*panes, target_pane]: self.assertEqual(process.wait(timeout=3),0)
        for name in 'abcd': self.assert_terminal_restored(name)
        receipt=self.receipt()
        self.assertEqual(receipt['mode'],'account-change')
        self.assertEqual(len(receipt['stopped_cli']),4)
        # Parallel: every pane gets its first Ctrl+C before any pane has quit.
        events=self.state()['events']
        first_exit=next(i for i,e in enumerate(events) if e[0]=='exited')
        keyed={e[1] for e in events[:first_exit] if e[0]=='send-keys'}
        self.assertEqual(keyed,set('abcd'))
        self.assertLess(elapsed,6)
        self.assertEqual(len([e for e in self.state()['events'] if e[0]=='daemon-stopped']),4)

    def test_non_interactive_subcommands_never_switch(self):
        first,second=self.setup_accounts()
        old=self.start('a','codex',first)
        for extra in (['exec','--once'],['--version'],['mcp','list','--once']):
            result=self.short('cod','secondary','--',*extra,terminal=False)
            self.assertEqual(json.loads(result.stdout)['home'],str(second))
        self.assertIsNone(old.poll())
        events=self.state()['events']
        self.assertFalse(any(e[0] in {'send-keys','exited','daemon-stopped'} for e in events))
        self.assertIn('selected: primary',self.short('cod','status').stdout)

    def test_claude_closes_old_sessions_and_execs_only_in_the_requesting_terminal(self):
        first,second=self.setup_accounts('claude')
        old=self.start('a','claude',first)
        self.short('cc','secondary')
        self.assertEqual(old.wait(timeout=3),0)
        self.assert_terminal_restored('a')
        self.assertEqual(self.receipt('claude')['state'],'exec-admitted')
        self.assertEqual(self.record(second)['home'],str(second))
        self.assertFalse(any(e[0].startswith('daemon-') for e in self.state()['events']))

    def test_zombie_cli_is_already_stopped_for_both_services(self):
        self.state(include_zombies=True)
        for service,alias in [('codex','cod'),('claude','cc')]:
            first,second=self.setup_accounts(service)
            old=self.start(service,service,first)
            self.short(alias,'secondary')
            fields=Path('/proc/'+str(old.pid)+'/stat').read_text().rsplit(')',1)[1].split()
            self.assertEqual(fields[0],'Z')
            self.assertEqual(self.receipt(service)['state'],'exec-admitted')
            self.assertEqual(self.record(second)['home'],str(second))
            self.assertEqual(old.wait(timeout=3),0)

    def test_codex_outside_herdr_is_refused_before_any_cli_or_daemon_stops(self):
        first,_=self.setup_accounts()
        a=self.start('a','codex',first); b=self.start('b','codex',first,managed=False)
        result=self.short('cod','secondary',ok=False)
        self.assertIn('outside Herdr',result.stderr)
        self.assertEqual(self.receipt()['state'],'failed')
        self.assertIsNone(a.poll()); self.assertIsNone(b.poll())
        events=self.state()['events']
        self.assertFalse(any(e[0] in {'exited','send-keys','daemon-stopped'} for e in events))

    def test_old_codex_pane_gets_its_terminal_back(self):
        first,second=self.setup_accounts()
        old=self.start('a','codex',first)
        self.short('cod','secondary')
        old.wait(timeout=3)
        self.assert_terminal_restored('a')
        self.assertEqual(old.returncode,0)
        events=self.state()['events']
        self.assertIn(['exited','a','ctrl+c'],events)
        self.assertEqual(self.record(second)['home'],str(second))

    def test_failed_stop_receipt_records_each_actual_outcome(self):
        first,second=self.setup_accounts()
        quits=self.start('a','codex',first); stuck=self.start('b','codex',first)
        with self.locked_state() as data: data['panes']['b']['stubborn']=True
        self.short('cod','secondary',ok=False)
        self.assertEqual(quits.wait(timeout=3),0); self.assertIsNone(stuck.poll())
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'failed')
        states={row['pid']:row['state'] for row in receipt['stopped_cli']}
        self.assertEqual(states,{quits.pid:'exited',stuck.pid:'running'})
        self.assertEqual({row['state'] for row in receipt['stopped_daemon']},{'running'})

    def test_key_is_not_sent_when_the_cli_exits_during_the_foreground_query(self):
        client={'pid':202,'start':5,'session':'fx','pane':'p','state':'planned'}
        births=iter([5,5,None])
        with mock.patch.object(lifecycle,'identity',side_effect=lambda pid: next(births,None)), \
                mock.patch.object(lifecycle.Herdr,'foreground',
                                  side_effect=lambda *a, seen=iter([{202}]): next(seen,set())), \
                mock.patch.object(lifecycle.Herdr,'send_ctrl_c') as sent:
            lifecycle.exit_in_band([client],1)
        sent.assert_not_called()
        self.assertEqual(client['state'],'exited')

    def test_flags_after_the_official_separator_are_prompt_text(self):
        import short_commands
        for service,values in [('codex',['--','--help']),('claude',['--','-p']),('codex',['--','exec'])]:
            self.assertFalse(short_commands.passes_through(service,values),values)
        for service,values in [('codex',['exec','--','x']),('codex',['--version']),('claude',['-p','hi'])]:
            self.assertTrue(short_commands.passes_through(service,values),values)

    def test_unregistered_cli_aborts_before_touching_other_clients(self):
        first,_=self.setup_accounts()
        a=self.start('a','codex',first)
        foreign=self.home/'unregistered'; foreign.mkdir(mode=0o700)
        b=self.start('b','codex',foreign)
        # No record can authorize terminating the foreign-home managed daemon.
        self.short('cod','secondary',ok=False)
        self.assertEqual(self.receipt()['state'],'failed')
        self.assertIsNone(a.poll()); self.assertIsNone(b.poll())
        self.assertFalse(any(e[0]=='exited' for e in self.state()['events']))

    def test_failed_stop_preserves_selection_and_starts_nothing(self):
        first,second=self.setup_accounts()
        old=self.start('a','codex',first)
        self.state(stubborn=True)
        result=self.short('cod','secondary',ok=False)
        self.assertIn('did not quit',result.stderr)
        self.assertEqual(self.receipt()['state'],'failed')
        self.assertIsNone(old.poll())
        self.assertIn('selected: primary',self.short('cod','status').stdout)
        self.assertFalse((second/'called.json').exists())

    def test_missing_target_login_fails_before_stopping_and_wrapper_conflicts(self):
        first,second=self.setup_accounts()
        old=self.start('a','codex',first)
        (second/'auth.json').unlink()
        self.short('cod','secondary',ok=False)
        self.assertIsNone(old.poll())
        existing=self.root/'codex'; existing.write_text('mine')
        self.call('codex','bind-current',existing,ok=False)
        self.assertEqual(existing.read_text(),'mine')

    def test_switch_from_inside_a_cli_is_rejected_before_termination(self):
        first,_=self.setup_accounts()
        old=self.start('caller','codex',first,extra_env={
            'FX_SWITCH_ON_START':'1','FX_FLIPAUTH':str(self.program)})
        self.wait_file(first/'nested-result',old)
        result=json.loads((first/'nested-result').read_text())
        self.assertNotEqual(result['rc'],0)
        self.assertIn('separate terminal',result['error'])
        self.assertIsNone(old.poll())
        self.assertFalse(any(e[0]=='exited' for e in self.state()['events']))

    def test_non_terminal_switch_is_rejected_before_termination(self):
        first,_=self.setup_accounts()
        old=self.start('a','codex',first)
        result=self.short('cod','secondary',terminal=False,ok=False)
        self.assertIn('requires a terminal',result.stderr)
        self.assertIsNone(old.poll())

    def test_repeated_same_account_commands_keep_the_daemon(self):
        first,_=self.setup_accounts()
        self.short('cod','primary')
        self.short('cod','primary')
        events=self.state()['events']
        self.assertEqual(len([e for e in events if e[:2]==['invoked',str(first)]]),2)
        self.assertFalse(any(e[0]=='daemon-stopped' for e in events))
        starts=[e for e in events if e[0]=='daemon-started' and e[1]=='server']
        self.assertEqual(len(starts),1)

    def test_switch_back_stops_the_other_accounts_daemon(self):
        first,second=self.setup_accounts()
        self.short('cod','secondary')
        self.short('cod','primary')
        events=self.state()['events']
        stopped=[e for e in events if e[0]=='daemon-stopped']
        self.assertEqual([(e[1],e[2]) for e in stopped],[('updater',str(second)),('server',str(second))])
        self.assertEqual(self.receipt()['mode'],'account-change')

    def test_reused_pid_is_never_signaled(self):
        with mock.patch.object(lifecycle,'identity',return_value=99), \
                mock.patch.object(lifecycle.os,'pidfd_open') as opened, \
                mock.patch.object(lifecycle.signal,'pidfd_send_signal') as signaled:
            with self.assertRaises(accounts.Refused): lifecycle.terminate(202,5,.1)
        opened.assert_not_called(); signaled.assert_not_called()

    def test_pid_change_after_handle_open_is_not_signaled(self):
        with mock.patch.object(lifecycle,'identity',side_effect=[5,99]), \
                mock.patch.object(lifecycle.os,'pidfd_open',return_value=123), \
                mock.patch.object(lifecycle.os,'close'), \
                mock.patch.object(lifecycle.signal,'pidfd_send_signal') as signaled:
            with self.assertRaises(accounts.Refused): lifecycle.terminate(202,5,.1)
        signaled.assert_not_called()

    def test_unexpected_process_prevents_daemon_shutdown(self):
        with mock.patch.object(lifecycle,'processes',return_value={202:{'start':5}}), \
                mock.patch.object(lifecycle,'verified_daemons',return_value=set()), \
                mock.patch.object(lifecycle.os,'pidfd_open') as opened:
            with self.assertRaises(accounts.Refused):
                lifecycle.stop_managed_daemons('codex',self.root/'registry',{},.1)
        opened.assert_not_called()

    def test_simultaneous_switches_either_launch_or_report_a_process_race(self):
        first,_=self.setup_accounts()
        commands=[]
        terminals=[]
        try:
            for _ in range(2):
                master,slave=pty.openpty(); terminals += [master,slave]
                commands.append(subprocess.Popen([str(self.program),'cod','primary','--','--once'],
                    env=self.env,stdin=slave,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
            admitted=0
            for command in commands:
                _,error=command.communicate(timeout=12)
                if command.returncode == 0:
                    admitted += 1
                else:
                    self.assertIn('flipauth:',error)
                    self.assertTrue(any(word in error for word in ('appeared','unexpected','changed','remain')),error)
        finally:
            for fd in terminals: os.close(fd)
            for command in commands:
                if command.poll() is None: command.kill(); command.wait()
        events=self.state()['events']
        self.assertGreaterEqual(admitted,1)
        self.assertEqual(len([e for e in events if e[:2]==['invoked',str(first)]]),admitted)

    def test_working_codex_interrupts_with_esc_and_recovers_from_task_modal(self):
        first,second=self.setup_accounts()
        working_pane=self.start('w','codex',first)
        modal_pane=self.start('m','codex',first)
        with self.locked_state() as data:
            data['panes']['m']['status']='task_modal'
        saved=self.env['FLIPAUTH_SWITCH_STOP_TIMEOUT']
        self.env['FLIPAUTH_SWITCH_STOP_TIMEOUT']='5'
        try:
            self.short('cod','secondary')
        finally:
            self.env['FLIPAUTH_SWITCH_STOP_TIMEOUT']=saved
        self.assertEqual(working_pane.wait(timeout=3),0)
        self.assertEqual(modal_pane.wait(timeout=3),0)
        self.assert_terminal_restored('w')
        self.assert_terminal_restored('m')
        events=self.state()['events']
        self.assertIn(['esc','w','working'],events)
        self.assertNotIn(['ctrl+c','w','working'],events)
        self.assertIn(['esc','m','task_modal'],events)
        self.assertIn(['esc','m','working'],events)
        self.assertIn(['exited','w','ctrl+c'],events)
        self.assertIn(['exited','m','ctrl+c'],events)
        self.assertEqual(self.record(second)['home'],str(second))

    def test_non_working_status_keeps_ctrl_c_only(self):
        client={'pid':202,'start':5,'session':'fx','pane':'p','state':'planned'}
        births=iter([5,5,5,5,None])
        with mock.patch.object(lifecycle,'identity',side_effect=lambda pid: next(births,None)), \
                mock.patch.object(lifecycle.Herdr,'foreground',side_effect=[{202},set()]), \
                mock.patch.object(lifecycle.Herdr,'pane_statuses',return_value={'p':'blocked'}), \
                mock.patch.object(lifecycle.Herdr,'send_esc') as sent_esc, \
                mock.patch.object(lifecycle.Herdr,'send_ctrl_c') as sent_ctrl_c:
            lifecycle.exit_in_band([client],1)
        sent_esc.assert_not_called()
        sent_ctrl_c.assert_called_once_with(client)
        self.assertEqual(client['state'],'exited')

    def test_send_key_rejection_after_cli_exit_finishes_cleanly(self):
        client={'pid':203,'start':5,'session':'fx','pane':'p','state':'planned'}
        rejected=False
        draining=0
        def fake_identity(pid):
            nonlocal draining
            if not rejected: return 5
            draining += 1
            return 5 if draining <= 2 else None
        def fake_send(target):
            nonlocal rejected
            if not rejected and client.get('keys_sent',0) == 0:
                return
            rejected=True
            raise accounts.Refused('Herdr command failed; inspect receipt before retrying')
        with mock.patch.object(lifecycle,'identity',side_effect=fake_identity), \
                mock.patch.object(lifecycle.Herdr,'foreground',side_effect=[{203},{203},set()]), \
                mock.patch.object(lifecycle.Herdr,'pane_statuses',return_value={'p':'idle'}), \
                mock.patch.object(lifecycle.Herdr,'send_ctrl_c',side_effect=fake_send):
            lifecycle.exit_in_band([client],2)
        self.assertEqual(client['state'],'exited')
        self.assertEqual(client['keys_sent'],1)
        self.assertEqual(client['key_delivery'],'acknowledged')

    def test_send_key_rejection_before_first_key_clears_unconfirmed(self):
        client={'pid':204,'start':5,'session':'fx','pane':'p','state':'planned'}
        births=[5,5,5,5,None]
        def fake_identity(pid):
            return births.pop(0) if births else None
        with mock.patch.object(lifecycle,'identity',side_effect=fake_identity), \
                mock.patch.object(lifecycle.Herdr,'foreground',side_effect=[{204},set()]), \
                mock.patch.object(lifecycle.Herdr,'pane_statuses',return_value={'p':'idle'}), \
                mock.patch.object(lifecycle.Herdr,'send_ctrl_c',
                                  side_effect=accounts.Refused('Herdr command failed; inspect receipt before retrying')):
            lifecycle.exit_in_band([client],1)
        self.assertEqual(client['state'],'exited')
        self.assertNotIn('key_delivery',client)
        self.assertEqual(client.get('keys_sent',0),0)

    def test_send_key_rejection_while_cli_remains_alive_refuses(self):
        client={'pid':205,'start':5,'session':'fx','pane':'p','state':'planned'}
        with mock.patch.object(lifecycle,'identity',return_value=5), \
                mock.patch.object(lifecycle.Herdr,'foreground',return_value={205}), \
                mock.patch.object(lifecycle.Herdr,'pane_statuses',return_value={'p':'idle'}), \
                mock.patch.object(lifecycle.Herdr,'send_ctrl_c',
                                  side_effect=accounts.Refused('Herdr command failed; inspect receipt before retrying')):
            with self.assertRaisesRegex(accounts.Refused,'Herdr command failed'):
                lifecycle.exit_in_band([client],.2)
        self.assertEqual(client['state'],'planned')
        self.assertEqual(client['key_delivery'],'unconfirmed')


if __name__=='__main__': unittest.main(verbosity=2)
