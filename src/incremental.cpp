// Fixed-start witness-based SIPP-IP repair. See docs/repair-design.md.
#include "model.hpp"
#include <limits>
#include <stdexcept>
#include <tuple>

struct Input {
    int h,w,horizon,sr,sc,so,sv,start,gr,gc,gv;
    long long limit;
    std::vector<std::string> grid;
    std::vector<Intervals> blocked;
};
struct Label { Node n; int producer=-1; bool live=true; unsigned long long generation=0; std::vector<int> owners; };
struct Expansion { int label,lo,hi; std::array<int,3> records{{-1,-1,-1}}; bool live=true; };
struct Projection { int owner,action; std::vector<int> outputs; bool live=true; unsigned long long stamp=0; };
struct Output {
    int lo,hi,dep_lo,dep_hi;
    bool operator==(const Output& b) const {return std::tie(lo,hi,dep_lo,dep_hi)==std::tie(b.lo,b.hi,b.dep_lo,b.dep_hi);}
};
struct RepairStats {
    Stats search;
    long long changed_cells=0,suspect=0,changed=0,reused=0,retired_labels=0,retired_owners=0,reactivated=0,created=0,compactions=0;
    bool unchanged=false,reset=false;
};
struct Incremental {
    Input env;
    Actions primitives=actions();
    std::vector<Label> labels;
    std::vector<Expansion> expansions;
    std::vector<Projection> records;
    std::vector<Intervals> closed;
    std::vector<std::vector<int>> candidates,owners,watch;
    // f, distance, -upper, label id, lower, upper, label scheduling generation
    using Entry=std::tuple<int,int,int,int,int,int,unsigned long long>;
    std::priority_queue<Entry,std::vector<Entry>,std::greater<Entry>> open;
    int root=-1,incumbent=-1,upper=std::numeric_limits<int>::max();
    unsigned long long epoch=0;
    bool completed=false;
    std::string last_status;
    RepairStats stats;
    double diff_us=0,repair_us=0,compaction_us=0;

    explicit Incremental(Input&& input):env(std::move(input)) {
        int n=env.h*env.w;
        closed.resize(n*8);candidates.resize(n*8);owners.resize(n*8);watch.resize(n);
        stats.reset=true;
        make_root();
    }
    int cell(int r,int c)const{return r*env.w+c;}
    int key(const Node& n)const{return (cell(n.r,n.c)*4+n.o)*2+n.v;}
    int distance(int r,int c)const{return std::abs(r-env.gr)+std::abs(c-env.gc);}
    bool inside(int r,int c)const{return r>=0&&r<env.h&&c>=0&&c<env.w;}
    bool goal(const Node& n)const{return n.r==env.gr&&n.c==env.gc&&n.v==env.gv;}
    int safe_end(int r,int c,int t)const{
        if(env.grid[r][c]=='#')return -1;
        for(auto [a,b]:env.blocked[cell(r,c)]){
            if(a<=t&&t<=b)return -1;
            if(a>t)return a-1;
        }
        return env.horizon;
    }
    bool same_query(const Input& b)const{
        return std::tie(env.h,env.w,env.horizon,env.sr,env.sc,env.so,env.sv,env.start,env.gr,env.gc,env.gv,env.grid)==
               std::tie(b.h,b.w,b.horizon,b.sr,b.sc,b.so,b.sv,b.start,b.gr,b.gc,b.gv,b.grid);
    }
    void consider_goal(int id){
        if(labels[id].live&&goal(labels[id].n)&&labels[id].n.lo<upper){incumbent=id;upper=labels[id].n.lo;}
    }
    void scan_goals(){
        incumbent=-1;upper=std::numeric_limits<int>::max();
        for(int o=0;o<4;++o)for(int id:candidates[(cell(env.gr,env.gc)*4+o)*2+env.gv])consider_goal(id);
    }
    void push_task(int id,int lo,int hi){
        const auto& l=labels[id];
        open.emplace(lo+5*distance(l.n.r,l.n.c),distance(l.n.r,l.n.c),-hi,id,lo,hi,l.generation);
        ++stats.search.generated;
        stats.search.peak_open=std::max(stats.search.peak_open,static_cast<long long>(open.size()));
    }
    void schedule(int id,bool reactivation=false){
        auto& l=labels[id];if(!l.live)return;
        ++l.generation; // revoke every old pending task for this raw label
        if(goal(l.n)){consider_goal(id);return;}
        auto pieces=subtract({{l.n.lo,l.n.hi}},closed[key(l.n)]);
        for(auto [a,b]:pieces){push_task(id,a,b);if(reactivation)++stats.reactivated;}
    }
    int add_label(Node n,int producer){
        int id=static_cast<int>(labels.size());
        Label l;l.n=n;l.producer=producer;labels.push_back(std::move(l));
        candidates[key(n)].push_back(id);++stats.created;
        schedule(id);return id;
    }
    void make_root(){
        int end=safe_end(env.sr,env.sc,env.start);
        if(end<env.start){root=-1;return;}
        root=add_label({env.sr,env.sc,env.so,env.sv,env.start,env.sv==0?end:env.start,-1,-1,0,0},-1);
    }
    bool static_valid(int owner,int action)const{
        const auto& e=expansions[owner];const auto& n=labels[e.label].n;
        for(const auto& t:primitives[n.o][n.v][action].touches){
            int r=n.r+t.dr,c=n.c+t.dc;
            if(!inside(r,c)||env.grid[r][c]=='#')return false;
        }
        return true;
    }
    void register_watch(int id){
        const auto& r=records[id];const auto& e=expansions[r.owner];const auto& n=labels[e.label].n;
        std::array<int,5> seen;int count=0;
        for(const auto& t:primitives[n.o][n.v][r.action].touches){
            int index=cell(n.r+t.dr,n.c+t.dc);
            if(std::find(seen.begin(),seen.begin()+count,index)==seen.begin()+count){seen[count++]=index;watch[index].push_back(id);}
        }
    }
    std::vector<Output> project(int owner,int action){
        ++stats.search.projections;
        // These inputs are copied: projection installation may grow the stores.
        const auto e=expansions[owner];const auto n=labels[e.label].n;
        const auto& p=primitives[n.o][n.v][action];
        Intervals departures{{e.lo,std::min(e.hi,env.horizon-p.duration)}};
        if(departures[0].first>departures[0].second)return {};
        for(const auto& t:p.touches){
            Intervals forbidden;
            for(auto [a,b]:env.blocked[cell(n.r+t.dr,n.c+t.dc)])forbidden.push_back({a-t.last,b-t.first});
            departures=subtract(departures,normalize(forbidden));
            if(departures.empty())return {};
        }
        std::vector<Output> result;
        for(auto [a,b]:departures){
            int lo=a+p.duration,hi=b+p.duration;
            if(p.velocity==0)hi=safe_end(n.r+p.dr,n.c+p.dc,hi);
            if(lo<=hi)result.push_back({lo,hi,a,b});
        }
        return result;
    }
    bool fingerprint_equal(int id,const std::vector<Output>& outputs)const{
        const auto& r=records[id];
        if(r.outputs.size()!=outputs.size())return false;
        for(size_t i=0;i<outputs.size();++i){
            const auto& l=labels[r.outputs[i]];
            if(!l.live||!(Output{l.n.lo,l.n.hi,l.n.dep_lo,l.n.dep_hi}==outputs[i]))return false;
        }
        return true;
    }
    void install(int id,const std::vector<Output>& outputs){
        const int owner=records[id].owner,action=records[id].action;
        const int parent=expansions[owner].label;const auto n=labels[parent].n;
        const auto& p=primitives[n.o][n.v][action];
        records[id].outputs.clear();
        for(const auto& out:outputs){
            int child=add_label({n.r+p.dr,n.c+p.dc,p.orientation,p.velocity,out.lo,out.hi,parent,action,out.dep_lo,out.dep_hi},id);
            records[id].outputs.push_back(child);
        }
    }
    void expand(int label,int lo,int hi){
        const auto n=labels[label].n;
        int owner=static_cast<int>(expansions.size());
        expansions.push_back({label,lo,hi});labels[label].owners.push_back(owner);owners[key(n)].push_back(owner);
        auto& c=closed[key(n)];c.push_back({lo,hi});c=normalize(c);
        ++stats.search.expansions;
        // Register the full footprint before any dynamic-obstacle early return.
        for(int action=0;action<static_cast<int>(primitives[n.o][n.v].size());++action){
            if(!static_valid(owner,action))continue;
            int id=static_cast<int>(records.size());records.push_back({owner,action,{}});
            expansions[owner].records[action]=id;register_watch(id);
            install(id,project(owner,action));
        }
    }
    void retire(const std::vector<int>& seeds,std::vector<int>& affected,std::vector<bool>& touched){
        std::vector<int> queue=seeds;
        for(size_t at=0;at<queue.size();++at){
            int id=queue[at];auto& l=labels[id];if(!l.live)continue;
            l.live=false;++stats.retired_labels;
            for(int owner:l.owners){
                auto& e=expansions[owner];if(!e.live)continue;
                e.live=false;++stats.retired_owners;int k=key(l.n);
                if(!touched[k]){touched[k]=true;affected.push_back(k);}
                for(int rid:e.records)if(rid>=0&&records[rid].live){
                    records[rid].live=false;
                    const auto& outputs=records[rid].outputs;queue.insert(queue.end(),outputs.begin(),outputs.end());
                }
            }
        }
    }
    void compact(){
        auto begin=Clock::now();
        std::vector<int> lm(labels.size(),-1),em(expansions.size(),-1),rm(records.size(),-1);
        int nl=0,ne=0,nr=0;
        for(size_t i=0;i<labels.size();++i)if(labels[i].live)lm[i]=nl++;
        for(size_t i=0;i<expansions.size();++i)if(expansions[i].live)em[i]=ne++;
        for(size_t i=0;i<records.size();++i)if(records[i].live)rm[i]=nr++;
        std::vector<Label> ls;ls.reserve(nl);std::vector<Expansion> es;es.reserve(ne);std::vector<Projection> rs;rs.reserve(nr);
        for(auto& l:labels)if(l.live){
            if(l.n.parent>=0){if(lm[l.n.parent]<0)throw std::runtime_error("live label has dead parent");l.n.parent=lm[l.n.parent];}
            if(l.producer>=0){if(rm[l.producer]<0)throw std::runtime_error("live label has dead producer");l.producer=rm[l.producer];}
            std::vector<int> live;for(int e:l.owners)if(em[e]>=0)live.push_back(em[e]);l.owners=std::move(live);ls.push_back(std::move(l));
        }
        for(auto& e:expansions)if(e.live){e.label=lm[e.label];for(auto& r:e.records)if(r>=0)r=rm[r];es.push_back(std::move(e));}
        for(auto& r:records)if(r.live){r.owner=em[r.owner];for(auto& l:r.outputs){if(lm[l]<0)throw std::runtime_error("live projection has dead output");l=lm[l];}r.stamp=0;rs.push_back(std::move(r));}
        root=root<0?-1:lm[root];incumbent=incumbent<0?-1:lm[incumbent];
        labels=std::move(ls);expansions=std::move(es);records=std::move(rs);
        candidates=std::vector<std::vector<int>>(closed.size());owners=std::vector<std::vector<int>>(closed.size());watch=std::vector<std::vector<int>>(env.h*env.w);
        for(int i=0;i<static_cast<int>(labels.size());++i)candidates[key(labels[i].n)].push_back(i);
        for(int i=0;i<static_cast<int>(expansions.size());++i)owners[key(labels[expansions[i].label].n)].push_back(i);
        for(int i=0;i<static_cast<int>(records.size());++i)register_watch(i);
        open={};scan_goals();
        for(int i=0;i<static_cast<int>(labels.size());++i)schedule(i);
        ++stats.compactions;compaction_us+=std::chrono::duration<double,std::micro>(Clock::now()-begin).count();
    }
    bool update(Input&& next){
        stats={};diff_us=repair_us=compaction_us=0;++epoch;
        auto begin=Clock::now();std::vector<int> cells;
        for(int i=0;i<env.h*env.w;++i)if(env.blocked[i]!=next.blocked[i])cells.push_back(i);
        env.limit=next.limit;
        stats.changed_cells=cells.size();
        diff_us=std::chrono::duration<double,std::micro>(Clock::now()-begin).count();
        if(cells.empty()){
            stats.unchanged=true;
            // next's duplicate tables are released before returning to the caller.
            next=Input{};
            return completed;
        }
        auto repairing=Clock::now();
        std::vector<int> suspect;
        for(int c:cells)for(int id:watch[c])if(records[id].live&&records[id].stamp!=epoch){records[id].stamp=epoch;suspect.push_back(id);}
        stats.suspect=suspect.size();
        env.blocked=std::move(next.blocked);next=Input{};
        std::vector<int> affected;std::vector<bool> touched(closed.size(),false);
        int root_end=safe_end(env.sr,env.sc,env.start),root_hi=env.sv==0?root_end:env.start;
        bool replace_root=(root<0)?root_end>=env.start:root_end<env.start||labels[root].n.hi!=root_hi;
        if(replace_root&&root>=0){retire({root},affected,touched);root=-1;}
        std::vector<std::pair<int,std::vector<Output>>> replacements;
        std::vector<int> seeds;
        for(int id:suspect){
            if(!records[id].live)continue;
            auto result=project(records[id].owner,records[id].action);
            if(fingerprint_equal(id,result)){++stats.reused;continue;}
            ++stats.changed;const auto& old=records[id].outputs;seeds.insert(seeds.end(),old.begin(),old.end());
            replacements.emplace_back(id,std::move(result));
        }
        retire(seeds,affected,touched);
        scan_goals();
        for(int k:affected){
            Intervals current;for(int id:owners[k])if(expansions[id].live)current.push_back({expansions[id].lo,expansions[id].hi});current=normalize(current);
            bool lost=!subtract(closed[k],current).empty();closed[k]=std::move(current);
            if(lost)for(int id:candidates[k])if(labels[id].live)schedule(id,true);
        }
        for(auto& replacement:replacements)if(records[replacement.first].live&&expansions[records[replacement.first].owner].live)install(replacement.first,replacement.second);
        if(replace_root)make_root();
        // Reclaim dead provenance, rebuilding the complete frontier with fresh handles.
        long long dead=0;for(const auto& l:labels)dead+=!l.live;
        if(dead>0&&dead*3>=static_cast<long long>(labels.size()))compact();
        repair_us=std::chrono::duration<double,std::micro>(Clock::now()-repairing).count();
        completed=false;return false;
    }
    std::pair<std::string,int> search(){
        if(root<0){completed=true;last_status="invalid_start";return {last_status,-1};}
        while(!open.empty()){
            const auto entry=open.top();open.pop();++stats.search.pops;
            int id=std::get<3>(entry),lo=std::get<4>(entry),hi=std::get<5>(entry);
            if(!labels[id].live||labels[id].generation!=std::get<6>(entry))continue;
            const auto n=labels[id].n;
            auto remaining=subtract({{lo,hi}},closed[key(n)]);
            if(remaining.empty())continue;
            if(remaining.size()!=1||remaining[0]!=Interval{lo,hi}){for(auto [a,b]:remaining)push_task(id,a,b);continue;}
            if(incumbent>=0&&std::get<0>(entry)>=upper){open.push(entry);completed=true;last_status="solved";return {last_status,incumbent};}
            if(stats.search.expansions>=env.limit){open.push(entry);completed=false;last_status="expansion_limit";return {last_status,-1};}
            expand(id,lo,hi);
        }
        completed=true;last_status=incumbent>=0?"solved":"no_path";
        return {last_status,incumbent};
    }
    std::vector<Step> reconstruct(int goal_id)const{
        std::vector<Step> result;int id=goal_id,t=labels[id].n.lo;
        while(labels[id].n.parent!=-1){
            const auto& n=labels[id].n;const auto& parent=labels[n.parent].n;
            if(!labels[id].live||!labels[n.parent].live)throw std::runtime_error("dead reconstruction witness");
            const auto& p=primitives[parent.o][parent.v][n.action];
            int departure=std::min(n.dep_hi,t-p.duration),arrival=departure+p.duration;
            if(departure<n.dep_lo||departure<parent.lo||departure>parent.hi)throw std::runtime_error("invalid departure witness");
            if(arrival<t)result.push_back({"wait",n.r,n.c,n.o,n.v,arrival,t,n.r,n.c,n.o,n.v});
            result.push_back({p.name,parent.r,parent.c,parent.o,parent.v,departure,arrival,n.r,n.c,n.o,n.v});t=departure;id=n.parent;
        }
        if(t>env.start)result.push_back({"wait",env.sr,env.sc,env.so,env.sv,env.start,t,env.sr,env.sc,env.so,env.sv});
        std::reverse(result.begin(),result.end());return result;
    }
};

double micros(Clock::time_point a,Clock::time_point b){return std::chrono::duration<double,std::micro>(b-a).count();}
bool read_input(Input& p,int h,int w){
    p.h=h;p.w=w;
    if(!(std::cin>>p.horizon>>p.sr>>p.sc>>p.so>>p.sv>>p.start>>p.gr>>p.gc>>p.gv>>p.limit))return false;
    if(h<1||w<1||h>1024||w>1024||p.horizon<0||p.horizon>10000000||p.start<0||p.start>p.horizon||p.limit<0||
       p.sr<0||p.sr>=h||p.sc<0||p.sc>=w||p.gr<0||p.gr>=h||p.gc<0||p.gc>=w||p.so<0||p.so>3||p.sv<0||p.sv>1||p.gv<0||p.gv>1)return false;
    p.grid.resize(h);for(auto& row:p.grid)if(!(std::cin>>row)||static_cast<int>(row.size())!=w||row.find_first_not_of(".#")!=std::string::npos)return false;
    p.blocked.resize(h*w);int count;if(!(std::cin>>count)||count<0)return false;
    for(int i=0;i<count;++i){int r,c,a,b;if(!(std::cin>>r>>c>>a>>b)||r<0||r>=h||c<0||c>=w||a<0||a>b||b>p.horizon)return false;p.blocked[r*w+c].push_back({a,b});}
    for(auto& b:p.blocked)b=normalize(b);
    return true;
}
int main(){
    std::ios::sync_with_stdio(false);std::unique_ptr<Incremental> planner;int h,w;
    while(std::cin>>h>>w){
        auto begin=Clock::now();Input input;if(!read_input(input,h,w))return 2;auto parsed=Clock::now();
        bool reuse=false;
        if(!planner||!planner->same_query(input))planner=std::make_unique<Incremental>(std::move(input));
        else reuse=planner->update(std::move(input));
        auto repaired=Clock::now();
        auto answer=reuse?std::make_pair(planner->last_status,planner->incumbent):planner->search();
        auto searched=Clock::now();
        auto steps=answer.second<0?std::vector<Step>{}:planner->reconstruct(answer.second);
        auto finished=Clock::now();const auto& p=*planner;const auto& s=p.stats;
        std::cout<<"{\"algorithm\":\"incremental-sipp-ip\",\"status\":\""<<answer.first<<"\",\"cost_ticks\":";
        if(answer.second<0)std::cout<<"null";else std::cout<<p.labels[answer.second].n.lo;
        std::cout<<",\"setup_us\":"<<micros(begin,parsed)<<",\"diff_us\":"<<p.diff_us<<",\"repair_us\":"<<p.repair_us
                 <<",\"maintenance_us\":"<<micros(parsed,repaired)<<",\"compaction_us\":"<<p.compaction_us
                 <<",\"search_us\":"<<micros(repaired,searched)<<",\"reconstruction_us\":"<<micros(searched,finished)
                 <<",\"teardown_us\":0,\"total_us\":"<<micros(begin,finished)
                 <<",\"expansions\":"<<s.search.expansions<<",\"projections\":"<<s.search.projections<<",\"generated\":"<<s.search.generated
                 <<",\"queue_pops\":"<<s.search.pops<<",\"peak_open\":"<<s.search.peak_open
                 <<",\"changed_cells\":"<<s.changed_cells<<",\"suspect_projections\":"<<s.suspect
                 <<",\"changed_projections\":"<<s.changed<<",\"reused_projections\":"<<s.reused
                 <<",\"retired_labels\":"<<s.retired_labels<<",\"retired_owners\":"<<s.retired_owners
                 <<",\"reactivated_intervals\":"<<s.reactivated<<",\"created_labels\":"<<s.created
                 <<",\"compactions\":"<<s.compactions<<",\"stored_labels\":"<<p.labels.size()<<",\"stored_projections\":"<<p.records.size()
                 <<",\"unchanged_forecast\":"<<(s.unchanged?"true":"false")<<",\"reset\":"<<(s.reset?"true":"false")<<",\"steps\":[";
        bool comma=false;for(const auto& step:steps){if(comma)std::cout<<',';comma=true;
            std::cout<<"{\"action\":\""<<step.action<<"\",\"from\":["<<step.r<<','<<step.c<<','<<step.o<<','<<step.v<<"],\"to\":["<<step.nr<<','<<step.nc<<','<<step.no<<','<<step.nv<<"],\"start\":"<<step.begin<<",\"end\":"<<step.end<<'}';}
        std::cout<<"]}\n"<<std::flush;
    }
    return std::cin.eof()?0:2;
}
