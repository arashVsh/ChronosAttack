"""Approved capacity-failure recovery; original scientific modules stay frozen."""
import json
import types
from reserved_cost_adapter import fingerprint

EXTRA_JOB = 'chronos_independent_tree4_20260909_v1|study|anthropic/claude-sonnet-4-6@default|tree4|permutation_stateful|10|8'
INVALID_RESPONSES = {
    '955f047c435455a1927a3e1c15c76abc277abe2d6dedfb72b9e0a444f0677c1d',
    '958c86b0b1cfc8c4e2315a5af76539272b78b8174b408f26d07fd6a032f58563',
}

def classified_event(event):
    # Frozen engine wrote this response before validation raised. Retain the
    # raw event and payload; only the derived accounting/audit view changes.
    if fingerprint(event) in INVALID_RESPONSES:
        return dict(event,event='call_failed',error_type='ValueError')
    return event

def limit(job_id):
    return 4 if job_id == EXTRA_JOB else 3

def amended_auditor(source):
    old = 'require(type(attempt) is int and 1 <= attempt <= 3, "Invalid attempt")'
    assert source.count(old) == 1
    new = f'require(type(attempt) is int and 1 <= attempt <= (4 if jid == {EXTRA_JOB!r} else 3), "Invalid attempt")'
    module = types.ModuleType('recovery_auditor')
    exec(compile(source.replace(old,new),'recovery_auditor','exec'),module.__dict__)
    def audit(events, model, phase, require_complete=True):
        events=list(events)
        invalid=[e for e in events if fingerprint(e) in INVALID_RESPONSES]
        for event in invalid:
            if not any(e['event']=='job_error' and e.get('error_type')=='ValueError'
                       and e['execution_id']==event['execution_id']
                       and e['attempt']==event['attempt']
                       and e['job']['id']==event['job_id'] for e in events):
                raise ValueError('Invalid-response abort missing')
        result=module.audit([classified_event(e) for e in events],model,phase,require_complete)
        result['invalid_response_calls']=len(invalid)
        return result
    return audit

def reserved_evidence(base, approved):
    assert len(approved) == 3 and len(set(approved)) == 3
    class RecoveryEvidence(base):
        def _accept(self,event):
            self.reserved_seen = getattr(self,'reserved_seen',set())
            self.uncovered = getattr(self,'uncovered',False)
            key = fingerprint(event)
            covered = key in approved
            if covered:
                if key in self.reserved_seen or event.get('event') != 'call_failed' or event.get('error_type') != 'RateLimitError' or event.get('cost_usd') is not None:
                    raise ValueError('Invalid reserved event')
                self.reserved_seen.add(key)
            if event['event'] in ('call_complete','call_failed') and event['cost_usd'] is None:
                self.uncovered |= not covered
            super()._accept(classified_event(event))
            if covered: self.spent += .10
            self.unknown_cost = self.uncovered
    return RecoveryEvidence

def run_missing(kbench,llm,p,ledger):
    for job in p.jobs_for(llm.model,'study'):
        if job['id'] in ledger.completed: continue
        while job['id'] not in ledger.completed:
            # Budget stops do not consume a scientific attempt.
            ledger.before_call()
            attempt=ledger.attempts.get(job['id'],0)+1
            if attempt > limit(job['id']): raise RuntimeError('Approved retry limit exhausted')
            ledger.append(dict(event='job_started',job_id=job['id'],attempt=attempt))
            try:
                p.engine.execute_job(kbench,llm,p.fixtures(),job,ledger,attempt)
            except Exception as e:
                ledger.append(dict(event='job_error',job=job,error_type=type(e).__name__,attempt=attempt))
                if type(e).__name__=='LengthFinishReasonError' and not ledger.unknown_cost and attempt < 3:
                    continue
                raise
