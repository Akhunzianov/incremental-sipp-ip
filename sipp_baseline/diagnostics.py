"""Change locality and repair costs; no planner decisions depend on these metrics."""
import statistics

from .events import effective_reservations

PHASES = ('diff_us','recheck_us','retirement_us','coverage_restore_us',
          'installation_us','compaction_us','repair_us','maintenance_us','search_us')
COUNTERS = ('before_live_labels','before_live_owners','before_live_projections','before_covered_states',
            'retired_projections','retired_states','direct_invalidated_labels','root_replaced',
            'live_labels','live_owners','live_projections','covered_states','expanded_states')


def ratio(a,b):
    return a/b if b else None


def change_size(data,before,after):
    """Exact symmetric difference in free-cell/integer-tick occupancy."""
    if before is None:
        return {'reservation_changed_cells':0,'changed_cell_ticks':0,'change_first_tick':None,
                'change_last_tick':None,'changed_cell_fraction':0,'changed_cell_tick_fraction':0}
    a=dict(effective_reservations(data,before));b=dict(effective_reservations(data,after))
    cells=ticks=0;first=last=None
    for cell in a.keys()|b.keys():
        if a.get(cell)==b.get(cell):continue
        cells+=1;events={}
        for lo,hi in (*a.get(cell,()),*b.get(cell,())):
            events[lo]=events.get(lo,0)+1;events[hi+1]=events.get(hi+1,0)-1
        active=0;previous=None
        for t,delta in sorted(events.items()):
            if previous is not None and active==1 and t>previous:
                ticks+=t-previous
                first=previous if first is None else min(first,previous)
                last=t-1 if last is None else max(last,t-1)
            active+=delta;previous=t
    free=sum(row.count('.') for row in data['grid'])
    return {'reservation_changed_cells':cells,'changed_cell_ticks':ticks,'change_first_tick':first,
            'change_last_tick':last,'changed_cell_fraction':ratio(cells,free),
            'changed_cell_tick_fraction':ratio(ticks,free*(data['horizon']+1))}


def repair_metrics(base,inc):
    return {'suspect_projection_fraction':ratio(inc['suspect_projections'],inc['before_live_projections']),
            'retired_label_fraction':ratio(inc['retired_labels'],inc['before_live_labels']),
            'retired_owner_fraction':ratio(inc['retired_owners'],inc['before_live_owners']),
            'retained_projection_fraction':None if not inc['before_live_projections'] else 1-inc['retired_projections']/inc['before_live_projections'],
            'retained_coverage_fraction':None if not inc['before_covered_states'] else 1-inc['retired_states']/inc['before_covered_states'],
            'cascade_amplification':ratio(inc['retired_labels'],inc['direct_invalidated_labels']),
            'search_expansion_ratio':ratio(inc['expansions'],base['expansions']),
            'maintenance_time_fraction':ratio(inc['maintenance_us'],inc['total_us'])}


def aggregate_diagnostics(rows):
    fields = (*PHASES,'changed_cell_fraction','changed_cell_tick_fraction','suspect_projection_fraction',
              'retired_label_fraction','retired_owner_fraction','retained_projection_fraction',
              'retained_coverage_fraction','cascade_amplification','search_expansion_ratio','maintenance_time_fraction')
    return {key:statistics.median(values) if (values:=[r[key] for r in rows if r[key] is not None]) else None for key in fields}
