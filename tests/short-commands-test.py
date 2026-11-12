#!/usr/bin/env python3
"""Exercise short commands, wrappers and full switch jobs with real fake-CLI PIDs."""

import importlib.util
import json
import os
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
from fixture_helpers import state
service = Path(sys.argv[0]).name.split('-')[0]
directory = Path(os.environ['CODEX_HOME' if service == 'codex' else 'CLAUDE_CONFIG_DIR'])
args = sys.argv[1:]
record = {'home':str(directory),'args':args,'pid':os.getpid(),'cwd':os.getcwd()}
(directory/'called.json').write_text(json.dumps(record))
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
def cancel(sig,frame):
    with state() as data:
        data['events'].append(['cancel',pane])
        if not data.get('stubborn'): data['panes'][pane]['status'] = 'idle'
def end(sig,frame):
    with state() as data: data['events'].append(['exited',pane])
    sys.exit(0)
signal.signal(signal.SIGINT,cancel)
signal.signal(signal.SIGTERM,end)
(directory/('ready-'+pane)).touch()
if os.environ.get('FX_SWITCH_ON_START') and directory.name == '.codex':
    import subprocess
    subprocess.run([os.environ['FX_FLIPAUTH'],'cod','secondary'],capture_output=True)
while True: time.sleep(.02)
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
'''

HERDR = r'''#!/usr/bin/env python3
import json, os, signal, subprocess, sys
from fixture_helpers import state, alive
args=sys.argv[1:]
if args[:2] == ['--session','fixture']:
    args=args[2:]
elif args[:1] == ['--session']: sys.exit(2)
def output(data): print(json.dumps(data))
if args == ['session','list','--json']:
    output({'sessions':[{'name':'fixture','running':True}]})
elif args == ['api','snapshot']:
    with state() as data:
        agents=[{'agent':row['service'],'pane_id':pane,'cwd':row['cwd'],
                 'agent_status':row['status']} for pane,row in data['panes'].items() if row.get('managed',True)]
    output({'result':{'snapshot':{'agents':agents}}})
elif args[:2] == ['pane','process-info']:
    pane=args[args.index('--pane')+1]
    with state() as data:
        row=data['panes'][pane]; pid=row.get('pid')
        procs=[{'pid':pid,'name':row['service'],'cwd':row['cwd']}]
        if not pid or not alive(pid):
            if pid and data.get('include_zombies') and not row.get('reported_dead'):
                row['reported_dead']=True
                data['events'].append(['zombie-observed',pane])
            else:
                procs=[{'pid':7,'name':'bash'}]
    output({'result':{'process_info':{'foreground_processes':procs,'shell_pid':7}}})
elif args[:2] == ['agent','send-keys']:
    assert args[3:] == ['ctrl+c']
    with state() as data: pid=data['panes'][args[2]]['pid']
    os.kill(pid,signal.SIGINT); output({'result':{'delivered':True}})
elif args[:2] == ['agent','prompt']:
    assert args[3:] == ['/exit']
    with state() as data: pid=data['panes'][args[2]]['pid']
    os.kill(pid,signal.SIGTERM); output({'result':{'delivered':True}})
elif args[:2] == ['pane','run']:
    pane=args[2]
    with state() as data:
        data['events'].append(['run',pane]); uncertain=data.get('uncertain_admission',False)
    env=os.environ.copy(); env['FX_PANE']=pane
    subprocess.Popen(['/bin/sh','-c',args[3]],env=env,stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    if uncertain: sys.exit(1)
    output({'result':{'admitted':True}})
else: sys.exit(2)
'''


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

    def state(self, **values):
        # Tests only update metadata before submitting workers, never during mutation.
        data=json.loads(self.statefile.read_text()); data.update(values)
        self.statefile.write_text(json.dumps(data)); return data

    def cleanup_processes(self):
        data=json.loads(self.statefile.read_text())
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
            live=False
            for row in data['panes'].values():
                try:
                    fields=Path('/proc/'+str(row.get('pid'))+'/stat').read_text().rsplit(')',1)[1].split()
                    live=live or fields[0]!='Z'
                except FileNotFoundError: pass
            if not live: break
            time.sleep(.02)

    def short(self, service, *args, ok=True, **kwargs):
        result=subprocess.run([str(self.program),service,*map(str,args)], env=self.env,
                              capture_output=True,text=True,timeout=8,**kwargs)
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
        data=self.state(); cwd=self.root/('project '+pane); cwd.mkdir()
        data['panes'][pane]={'service':service,'cwd':str(cwd),'status':'working','managed':managed}
        self.state(**data)
        env={**self.env,'FX_PANE':pane, 'CODEX_HOME' if service=='codex' else 'CLAUDE_CONFIG_DIR':str(directory)}
        env.update(extra_env or {})
        process=subprocess.Popen([self.env['FLIPAUTH_'+service.upper()+'_BIN']],env=env,cwd=cwd,
                                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.originals=getattr(self,'originals',[])+[process]
        self.wait_file(directory/('ready-'+pane),process)
        return process

    def receipt(self, service='codex'):
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            paths=list((self.root/'registry/switches').glob(service+'-*.json'))
            if paths:
                path=max(paths,key=lambda p:p.stat().st_mtime)
                data=json.loads(path.read_text())
                if data['state'] in {'complete','failed','already-selected'}: return data
            time.sleep(.05)
        self.fail('switch worker did not finish')

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
            self.assertEqual(record['args'],['--no-daemon','--once','a b',"'",'$HOME'])
        self.assertFalse((self.home/'tripwire').exists())

    def test_busy_all_panes_stop_before_any_restart_and_other_service_survives(self):
        first,second=self.setup_accounts()
        claude=self.create('claude','other')
        a=self.start('a','codex',first); b=self.start('b','codex',first)
        other=self.start('c','claude',claude)
        self.short('cod','secondary')
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'complete',receipt)
        self.assertEqual(a.wait(timeout=3),0); self.assertEqual(b.wait(timeout=3),0)
        self.assertIsNone(other.poll())
        events=json.loads(self.statefile.read_text())['events']
        first_run=next(i for i,e in enumerate(events) if e[0]=='run')
        self.assertTrue(all(next(i for i,e in enumerate(events) if e==['exited',pane])<first_run for pane in ('a','b')))
        for target in receipt['panes']:
            self.assertEqual(target['state'],'home-verified')
            self.assertTrue(Path('/proc/'+str(target['new_pid'])).exists())
        self.assertEqual(self.record(second)['args'], ['--no-daemon'])
        self.assertEqual(self.short('cod','status').returncode,0)
        self.assertIn('selected: secondary',self.short('cod','status').stdout)
        # Repeated selection does not close/restart already-correct sessions.
        before=[e for e in events if e[0]=='run']
        self.short('cod','secondary')
        self.assertEqual(self.receipt()['state'],'already-selected')
        after=json.loads(self.statefile.read_text())['events']
        self.assertEqual(before,[e for e in after if e[0]=='run'])

    def test_claude_busy_switch_and_uncertain_admission_readback(self):
        first,second=self.setup_accounts('claude')
        self.start('a','claude',first)
        self.state(uncertain_admission=True)
        self.short('cc','secondary')
        receipt=self.receipt('claude')
        self.assertEqual(receipt['state'],'complete',receipt)
        events=json.loads(self.statefile.read_text())['events']
        self.assertEqual(len([e for e in events if e[0]=='run']),1)

    def test_exited_unreaped_cli_restarts_for_both_services(self):
        self.state(include_zombies=True)
        for service, alias in [('codex','cod'),('claude','cc')]:
            with self.subTest(service=service):
                first, second = self.setup_accounts(service)
                process = self.start(service,service,first)
                self.short(alias,'secondary')
                record = self.receipt(service)
                # Do not poll/wait/reap the original until after worker completion.
                fields=Path('/proc/'+str(process.pid)+'/stat').read_text().rsplit(')',1)[1].split()
                self.assertEqual(fields[0],'Z')
                self.assertEqual(record['state'],'complete',record)
                events=json.loads(self.statefile.read_text())['events']
                self.assertIn(['zombie-observed',service],events)
                self.assertEqual(len([e for e in events if e==['run',service]]),1)
                self.assertEqual(self.record(second)['home'],str(second))
                self.assertEqual(process.wait(timeout=3),0)

    def test_exit_between_process_scan_and_identity_check(self):
        first, second = self.setup_accounts()
        process = self.start('race','codex',first)
        start = lifecycle.identity(process.pid)
        target = {'session':'fixture','pane':'race','pid':process.pid,'start':start}
        herdr = lifecycle.Herdr()
        info = {'foreground_processes':[{'pid':process.pid}]}
        with mock.patch.object(herdr,'foreground',return_value=info), mock.patch.object(
                lifecycle,'processes',return_value={process.pid:{}}):
            # A live PID with a different birth identity must still block the action.
            with self.assertRaises(accounts.Refused):
                herdr.still_original({**target,'start':start+1},'codex')
            os.kill(process.pid,signal.SIGTERM)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                fields=Path('/proc/'+str(process.pid)+'/stat').read_text().rsplit(')',1)[1].split()
                if fields[0]=='Z': break
                time.sleep(.01)
            self.assertEqual(fields[0],'Z')
            # ps saw a live process, but it exited before the next /proc read.
            self.assertFalse(herdr.still_original(target,'codex'))
            process.wait(timeout=3)
            # Reaped between the same two observations is also an ordinary exit.
            self.assertFalse(herdr.still_original(target,'codex'))

    def test_unmanaged_process_aborts_before_touching_managed_pane(self):
        first,second=self.setup_accounts()
        a=self.start('a','codex',first)
        b=self.start('b','codex',first,managed=False)
        self.short('cod','secondary')
        record=self.receipt()
        self.assertEqual(record['state'],'failed')
        self.assertIn('unmanaged',record['error'])
        self.assertIsNone(a.poll()); self.assertIsNone(b.poll())
        self.assertFalse(any(e[0]=='cancel' for e in json.loads(self.statefile.read_text())['events']))

    def test_failed_stop_preserves_selection_and_starts_nothing(self):
        first,second=self.setup_accounts()
        a=self.start('a','codex',first)
        self.state(stubborn=True)
        self.short('cod','secondary')
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'failed')
        self.assertIsNone(a.poll())
        self.assertIn('selected: primary',self.short('cod','status').stdout)
        self.assertFalse(any(e[0]=='run' for e in json.loads(self.statefile.read_text())['events']))

    def test_missing_target_login_fails_before_stopping_and_wrapper_conflicts(self):
        first,second=self.setup_accounts()
        a=self.start('a','codex',first)
        (second/'auth.json').unlink()
        self.short('cod','secondary',ok=False)
        self.assertIsNone(a.poll())
        existing=self.root/'codex'; existing.write_text('mine')
        self.call('codex','bind-current',existing,ok=False)
        self.assertEqual(existing.read_text(),'mine')

    def test_worker_survives_the_cli_that_requested_its_own_switch(self):
        first,second=self.setup_accounts()
        caller=self.start('caller','codex',first,extra_env={
            'FX_SWITCH_ON_START':'1','FX_FLIPAUTH':str(self.program)})
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'complete',receipt)
        self.assertEqual(caller.wait(timeout=3),0)
        self.assertEqual(receipt['panes'][0]['pid'],caller.pid)
        self.assertNotEqual(receipt['worker_pid'],caller.pid)

    def test_same_target_queued_twice_does_not_restart_twice(self):
        first,second=self.setup_accounts()
        self.start('a','codex',first)
        self.short('cod','secondary')
        self.short('cod','secondary')
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            paths=list((self.root/'registry/switches').glob('codex-*.json'))
            records=[json.loads(p.read_text()) for p in paths]
            if len(records)==2 and all(r['state'] in {'complete','already-selected','failed'} for r in records): break
            time.sleep(.05)
        self.assertEqual(sorted(r['state'] for r in records),['already-selected','complete'])
        self.assertEqual(len([e for e in json.loads(self.statefile.read_text())['events'] if e[0]=='run']),1)

    def test_daemon_pid_reuse_after_preflight_never_opens_a_signal_handle(self):
        first, second = self.setup_accounts()
        jobs = self.root / 'registry/switches'
        jobs.mkdir()
        receipt = jobs / 'codex-reused.json'
        receipt.write_text(json.dumps({'target': 'secondary', 'arguments': [], 'state': 'queued'}))
        daemon = {'pid': 202, 'start': 5, 'home': str(first), 'argv': ['codex', 'app-server'],
                  'command': ['app-server', '--managed-daemon']}
        target = {'session': 'fixture', 'pane': 'a', 'pid': 101, 'start': 3,
                  'cwd': str(self.root), 'state': 'planned'}
        herdr = mock.Mock()
        herdr.plan.return_value = ([target], {101})
        with mock.patch.object(lifecycle, 'Herdr', return_value=herdr), \
                mock.patch.object(lifecycle, 'processes', side_effect=[
                    {101: {'pid': 101, 'start': 3}, 202: daemon},
                    {202: {**daemon, 'start': 99}}]), \
                mock.patch.object(lifecycle, 'verified_daemons', return_value={202}), \
                mock.patch.object(lifecycle, 'process_environment', return_value={}), \
                mock.patch.object(lifecycle, 'identity', return_value=99), \
                mock.patch.object(lifecycle.os, 'pidfd_open') as opened, \
                mock.patch.object(lifecycle.signal, 'pidfd_send_signal') as signaled:
            lifecycle.run_worker('codex', self.program, self.root / 'registry', receipt)
        result = json.loads(receipt.read_text())
        self.assertEqual(result['state'], 'failed')
        self.assertIn('changed since preflight', result['error'])
        opened.assert_not_called()
        signaled.assert_not_called()
        self.assertEqual(json.loads((self.root / 'registry/accounts.json').read_text())['selected']['codex'], 'primary')

    def test_final_sweep_rejects_extra_process_changed_birth_or_changed_pane(self):
        _, second = self.setup_accounts()
        target = {'session': 'fixture', 'pane': 'a', 'new_pid': 333, 'new_start': 9}
        fact = {'start': 9, 'home': str(second)}
        herdr = mock.Mock()
        herdr.foreground.return_value = {'foreground_processes': [{'pid': 333}]}
        with mock.patch.object(lifecycle, 'processes', return_value={333: fact}):
            lifecycle.verify_restarted_targets(herdr, [target], 'codex', second)
        for observed in ({333: fact, 444: fact}, {333: {**fact, 'start': 10}}):
            with self.subTest(observed=observed), mock.patch.object(lifecycle, 'processes', return_value=observed):
                with self.assertRaises(accounts.Refused):
                    lifecycle.verify_restarted_targets(herdr, [target], 'codex', second)
        herdr.foreground.return_value = {'foreground_processes': [{'pid': 444}]}
        with mock.patch.object(lifecycle, 'processes', return_value={333: fact}):
            with self.assertRaises(accounts.Refused):
                lifecycle.verify_restarted_targets(herdr, [target], 'codex', second)


if __name__=='__main__': unittest.main(verbosity=2)
