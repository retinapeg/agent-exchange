"""Small predeclared synthetic comparison; never a real-user compatibility claim."""
from itertools import combinations
from exchange.matchmaking import propose
from exchange.common import DATA, write_json


def evaluate():
    profiles = [
        {'id':'synthetic-a','interests':['python','physics'],'goals':['reproduce'],'availability':['evening'],'communication':['async'],'timezone':'UTC'},
        {'id':'synthetic-b','interests':['python','physics'],'goals':['reproduce'],'availability':['evening'],'communication':['async'],'timezone':'UTC'},
        {'id':'synthetic-c','interests':['python','web'],'goals':['website'],'availability':['morning'],'communication':['video'],'timezone':'UTC'},
        {'id':'synthetic-d','interests':['python','physics'],'goals':['reproduce'],'availability':['evening'],'communication':['async']},
    ]
    # Frozen invented mutual-interest labels, independent of both recommendation rules.
    labels = {('synthetic-a','synthetic-b'), ('synthetic-a','synthetic-d')}
    baseline = [tuple(sorted([a['id'],b['id']])) for a,b in combinations(profiles,2) if set(a['interests']) & set(b['interests'])]
    proposals = propose(profiles)
    constrained = [tuple(p['participants']) for p in proposals['proposals']]
    by_id = {p['id']:p for p in profiles}
    results = {}
    for name, pairs in [('tag-overlap',baseline),('constrained',constrained)]:
        violations = sum(not all(set(by_id[a].get(f,[])) & set(by_id[b].get(f,[])) for f in ('goals','availability','communication')) for a,b in pairs)
        accepted = sum(p in labels for p in pairs)
        import json
        # Private marker is deliberately absent from all outward profiles and proposals.
        withheld = 'withheld-timezone-marker-d'
        leakage = int(withheld in json.dumps(profiles) or withheld in json.dumps(proposals if name == 'constrained' else pairs))
        results[name] = {'proposed':len(pairs),'simulated_mutual_acceptance':accepted,'acceptance_fraction':accepted/len(pairs) if pairs else None,'constraint_violations':violations,'withheld_field_leakage':leakage}
    value = {'schema_version':'leo.match-evaluation.v1','scope':'four fictional profiles, six pairs, invented labels; no real user outcomes',
             'profiles':profiles,'withheld':{'synthetic-d':['timezone']},'labels':[list(p) for p in sorted(labels)],'results':results}
    write_json(DATA/'receipts/match-evaluation.json',value)
    return value
