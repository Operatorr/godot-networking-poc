"""The real status shape can straddle normal process teardown and guard publication."""
import unittest
import clean_run as live

class TerminalPollTests(unittest.TestCase):
    def test_missing_sockets_wait_only_after_scheduled_end_until_bounded_guard(self):
        cell=dict(namespace='clean-terminal-test',population=2,behavior='idle',revision='a'*40,
                  game_sha256='b'*64,bot_sha256='c'*64)
        live.configure_cell(cell)
        observed=dict(phase={'phase2_utc_ns':1},guard=None,bot_identity=None,sockets='')
        window=dict(start=60_000_000_001,end=360_000_000_001)
        self.assertEqual(live.bot_runtime_problem(observed,window,window['end']-1),'bot-runtime-identity-missing')
        self.assertIsNone(live.bot_runtime_problem(observed,window,window['end']+254_454_820))
        self.assertEqual(live.bot_runtime_problem(observed,window,window['end']+10_000_000_000),'bot-terminal-result-timeout')
        self.assertEqual(live.bot_runtime_problem(observed,None,window['end']+1),'bot-runtime-identity-missing')
        observed['bot_identity']={'pid':42}
        self.assertEqual(live.bot_runtime_problem(observed,window,window['end']-1),'bot-socket-observations-incomplete')
        observed['sockets']='omega-load-test\n skmem:(r0,rb212992,t0,tb999)\nomega-load-test\n skmem:(r0,rb212992,t0,tb212992)'
        self.assertEqual(live.bot_runtime_problem(observed,window,window['end']+1),'bot-effective-buffers-differ')
        observed['guard']={'reason':None,'exit':1}
        self.assertIsNone(live.bot_runtime_problem(observed,window,window['end']+20_000_000_000))
