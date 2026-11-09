"""Shared planning trigger: initial query, then effective prediction changes."""

POLICY = 'effective-prediction-change-v1'


def effective_reservations(data, forecast):
    cells = {}
    for r,c,a,b in forecast['reservations']:
        if data['grid'][r][c]=='.':
            cells.setdefault((r,c),[]).append((a,b))
    result = []
    for cell,intervals in sorted(cells.items()):
        merged = []
        for a,b in sorted(intervals):
            if merged and a<=merged[-1][1]+1:
                merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:
                merged.append((a,b))
        result.append((cell,tuple(merged)))
    return tuple(result)


def planning_events(data):
    """Keep source snapshots intact; return selected queries and decision ledger.

    Metadata, proposal outcomes and polling times do not trigger planning.
    Independent paper instances are separate problems and always run.
    """
    independent = data.get('metadata',{}).get('independent_instances',False)
    selected,decisions = [],[]
    previous = None
    source_id = None
    for i,forecast in enumerate(data['forecasts']):
        current = effective_reservations(data,forecast)
        invoked = i==0 or independent or current!=previous
        reason = 'initial' if i==0 else 'independent_instance' if independent else 'prediction_changed' if invoked else 'unchanged_prediction'
        if invoked:
            selected.append(forecast)
            source_id=forecast['id']
        decisions.append({'forecast_id':forecast['id'],'revision_tick':forecast.get('revision_tick'),
                          'planner_invoked':invoked,'reason':reason,'source_forecast_id':source_id})
        previous = current
    return selected,decisions


def reused_result(result):
    """A viewer observation, explicitly not a measured planner invocation."""
    row = dict(result)
    for key in row:
        if key.endswith('_us') or key in ('expansions','projections','generated','queue_pops','peak_open'):
            row[key]=0
    row['planner_invoked']=False
    return row
