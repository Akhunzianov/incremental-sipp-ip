// Offline experiment. The old immutable witness graph is consumed at each miss.
#define SIPP_LIBRARY
#define SIPP_ADAPTIVE
#define SIPP_WITNESS_AUDIT
#include "incremental.cpp"
#include <deque>

Intervals intersect_domain(const Intervals& xs,int lo,int hi) {
    Intervals result;
    for(auto [a,b]:xs) {
        if(a>hi) break;
        if(b>=lo) result.push_back({std::max(lo,a),std::min(hi,b)});
    }
    return result;
}

struct WitnessAudit {
    Incremental& old;
    const Input& next;
    std::vector<bool> changed;
    std::vector<Intervals> reached,pending,eligible;
    std::deque<int> queue;
    // -1 means unvisited; 1 means every outgoing action still has its full fingerprint.
    std::vector<signed char> intact;
    std::vector<std::vector<Output>> retained;
    std::vector<bool> recomputed;
    long long whole=0,partial=0,valid=0,label_whole=0,label_partial=0;

    WitnessAudit(Incremental& source,const Input& input):old(source),next(input),
        changed(input.blocked.size()),reached(source.closed.size()),pending(reached.size()),
        eligible(reached.size()),intact(source.expansions.size(),-1),
        retained(source.records.size()),recomputed(retained.size()) {}

    void reach(int key,int lo,int hi) {
        auto delta=subtract({{lo,hi}},reached[key]);
        if(delta.empty()) return;
        if(pending[key].empty()) queue.push_back(key);
        for(auto interval:delta) {
            pending[key].push_back(interval);
            reached[key].push_back(interval);
        }
        reached[key]=normalize(std::move(reached[key]));
    }

    void check_actions(int owner) {
        const auto& e=old.expansions[owner];
        const auto& n=old.labels[e.label].n;
        intact[owner]=1;
        for(int rid:e.records) {
            if(rid<0) continue; // static map and primitives are identical
            const auto& record=old.records[rid];
            const auto& p=old.primitives[n.o][n.v][record.action];
            bool dirty=false;
            for(const auto& t:p.touches) dirty|=changed[old.cell(n.r+t.dr,n.c+t.dc)];
            if(!dirty) continue;
            auto current=old.project_result(owner,record.action);
            if(old.fingerprint_equal(rid,current)) continue;
            intact[owner]=0;
            recomputed[rid]=true;
            for(int child:record.outputs) {
                const auto& witness=old.labels[child].n;
                for(const auto& now:current) {
                    int a=std::max(witness.dep_lo,now.dep_lo),b=std::min(witness.dep_hi,now.dep_hi);
                    if(a<=b) retained[rid].push_back({a+p.duration,std::min(witness.hi,now.hi),a,b});
                }
            }
        }
    }

    void propagate(int key, const Intervals& delta) {
        for(int owner:old.owners[key]) {
            const auto& e=old.expansions[owner];
            if(!e.live) continue;
            auto source=intersect_domain(delta,e.lo,e.hi);
            if(source.empty()) continue;
            if(intact[owner]<0) check_actions(owner);
            const auto& n=old.labels[e.label].n;
            for(int rid:e.records) {
                if(rid<0) continue;
                const auto& rec=old.records[rid];
                const auto& p=old.primitives[n.o][n.v][rec.action];
                int dest=(old.cell(n.r+p.dr,n.c+p.dc)*4+p.orientation)*2+p.velocity;
                auto follow=[&](int dep_lo,int dep_hi,int end) {
                    for(auto [a,b]:source) {
                        int lo=std::max(a,dep_lo),hi=std::min(b,dep_hi);
                        if(lo<=hi) reach(dest,lo+p.duration,p.velocity?hi+p.duration:end);
                    }
                };
                if(recomputed[rid]) {
                    for(const auto& out:retained[rid]) follow(out.dep_lo,out.dep_hi,out.hi);
                } else {
                    for(int child:rec.outputs) {
                        const auto& out=old.labels[child].n;
                        follow(out.dep_lo,out.dep_hi,out.hi);
                    }
                }
            }
        }
    }

    void discover() {
        for(size_t i=0;i<changed.size();++i) changed[i]=old.env.blocked[i]!=next.blocked[i];
        old.env.blocked=next.blocked; // project_result now checks current occupancy
        int end=old.safe_end(next.sr,next.sc,next.start);
        if(end>=next.start) reach((old.cell(next.sr,next.sc)*4+next.so)*2+next.sv,
                                  next.start,next.sv?next.start:end);
        while(!queue.empty()) {
            int key=queue.front(); queue.pop_front();
            Intervals delta;
            pending[key].swap(delta);
            propagate(key,normalize(std::move(delta)));
        }
    }

    void classify() {
        for(const auto& l:old.labels) if(l.live) {
            const auto& n=l.n;
            auto xs=intersect_domain(reached[old.key(n)],n.lo,n.hi);
            if(xs.size()==1 && xs[0]==Interval{n.lo,n.hi}) ++label_whole;
            else if(!xs.empty()) ++label_partial;
        }
        for(size_t id=0;id<old.expansions.size();++id) {
            const auto& e=old.expansions[id];
            if(!e.live) continue;
            int key=old.key(old.labels[e.label].n);
            auto xs=intersect_domain(reached[key],e.lo,e.hi);
            if(xs.size()==1 && xs[0]==Interval{e.lo,e.hi}) {
                ++whole;
                if(intact[id]==1) {++valid; eligible[key].push_back({e.lo,e.hi});}
            } else if(!xs.empty()) ++partial;
        }
        for(auto& xs:eligible) if(!xs.empty()) xs=normalize(std::move(xs));
    }
};

int main(int argc,char** argv) {
    const bool dump=argc==2 && std::string(argv[1])=="--dump-support";
    if(argc!=1 && !dump) return 2;
    std::ios::sync_with_stdio(false);
    std::unique_ptr<Incremental> old;
    int h,w;
    while(std::cin>>h>>w) {
        Input input;
        if(!read_input(input,h,w)) return 2;
        std::vector<Step> suffix;
        if(old && old->completed && old->incumbent>=0 &&
           certified_suffix(old->env,old->upper,old->primitives,[&](){return old->reconstruct(old->incumbent);},input,suffix)) {
            std::cout<<"{\"audited\":false,\"status\":\"solved\",\"cost_ticks\":"<<old->upper<<"}\n";
            continue;
        }
        Planner p;
        std::tie(p.h,p.w,p.horizon,p.sr,p.sc,p.so,p.sv,p.start,p.gr,p.gc,p.gv,p.limit)=
            std::tie(input.h,input.w,input.horizon,input.sr,input.sc,input.so,input.sv,input.start,input.gr,input.gc,input.gv,input.limit);
        p.grid=input.grid;p.blocked=input.blocked;p.closed.resize(h*w*8);
        auto [status,goal]=p.search();
        int cost=goal<0?-1:p.nodes[goal].lo;
        std::cout<<"{\"status\":\""<<status<<"\",\"cost_ticks\":"<<(goal<0?"null":std::to_string(cost));
        if(old) {
            if(old->env.grid!=input.grid || old->env.horizon!=input.horizon || input.start<=old->env.start) return 3;
            auto start=Clock::now();
            WitnessAudit audit(*old,input);
            audit.discover();
            auto discovered=Clock::now();
            audit.classify();
            auto stop=Clock::now();
            long long overlaps=0,covered=0;
            double credit=0,full_credit=0,total=0;
            for(const auto& fresh:p.trace) {
                total+=fresh.us;
                auto xs=intersect_domain(audit.eligible[fresh.key],fresh.lo,fresh.hi);
                if(xs.empty()) continue;
                ++overlaps;credit+=fresh.us;
                if(xs.size()==1 && xs[0]==Interval{fresh.lo,fresh.hi}) {++covered;full_credit+=fresh.us;}
            }
            std::cout<<",\"audited\":true,\"labels\":"<<old->live_labels<<",\"whole_labels\":"<<audit.label_whole
                     <<",\"partial_labels\":"<<audit.label_partial<<",\"owners\":"<<old->live_owners
                     <<",\"whole\":"<<audit.whole<<",\"partial\":"<<audit.partial<<",\"eligible\":"<<audit.valid
                     <<",\"fresh\":"<<p.trace.size()<<",\"overlaps\":"<<overlaps<<",\"covered\":"<<covered
                     <<",\"discovery_us\":"<<micros(start,discovered)<<",\"audit_us\":"<<micros(start,stop)<<",\"credit_us\":"<<credit
                     <<",\"covered_us\":"<<full_credit<<",\"expansion_us\":"<<total;
            if(dump) {
                std::cout<<",\"support\":[";
                bool first=true;
                for(size_t k=0;k<audit.reached.size();++k) for(auto [a,b]:audit.reached[k]) {
                    if(!first) std::cout<<',';
                    first=false;
                    std::cout<<'['<<k<<','<<a<<','<<b<<']';
                }
                std::cout<<"],\"eligible_domains\":[";
                first=true;
                for(size_t id=0;id<old->expansions.size();++id) {
                    const auto& e=old->expansions[id];
                    int key=old->key(old->labels[e.label].n);
                    if(audit.intact[id]!=1 || !subtract({{e.lo,e.hi}},audit.reached[key]).empty()) continue;
                    if(!first) std::cout<<',';
                    first=false;
                    std::cout<<'['<<key<<','<<e.lo<<','<<e.hi<<']';
                }
                std::cout<<']';
            }
        } else std::cout<<",\"audited\":false";
        old=std::make_unique<Incremental>(std::move(input));
        auto answer=old->search();
        if(answer.first!=status || (answer.second<0?-1:old->labels[answer.second].n.lo)!=cost) return 4;
        std::cout<<"}\n";
    }
}
