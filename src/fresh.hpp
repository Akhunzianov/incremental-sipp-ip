#pragma once
#include "model.hpp"
#include "profile.hpp"
struct Planner {
    int h,w,horizon,sr,sc,so,sv,start,gr,gc,gv;
    long long limit;
    std::vector<std::string> grid;
    std::vector<Intervals> blocked, closed;
    std::vector<Node> nodes;
#ifdef SIPP_WITNESS_AUDIT
    struct TimedExpansion {int key,lo,hi; double us;};
    std::vector<TimedExpansion> trace;
#endif
    Actions primitives=actions(); Stats stats;
    using Entry=std::tuple<int,int,int,int>; // f, distance, -upper, stable node id
    std::priority_queue<Entry,std::vector<Entry>,std::greater<Entry>> open;
    bool inside(int r,int c) const { return r>=0 && c>=0 && r<h && c<w; }
    int cell(int r,int c) const { return r*w+c; }
    int key(const Node& n) const { return (cell(n.r,n.c)*4+n.o)*2+n.v; }
    int distance(int r,int c) const { return std::abs(r-gr)+std::abs(c-gc); }
    int safe_end(int r,int c,int t) const {
        int end=horizon;
        for(auto [a,b]:blocked[cell(r,c)]) {
            if(a<=t && t<=b) return -1;
            if(a>t) { end=a-1; break; }
        }
        return end;
    }
    void push(Node n) {
        PROFILE_PHASE(witness);
        if(n.lo>n.hi) return;
        int id=static_cast<int>(nodes.size()); nodes.push_back(n);
        { PROFILE_PHASE(queue); open.emplace(n.lo+5*distance(n.r,n.c),distance(n.r,n.c),-n.hi,id); }
        ++stats.generated;
        stats.peak_open=std::max(stats.peak_open,static_cast<long long>(open.size()));
    }
    void project(const Node& n,int parent,int action) {
        PROFILE_PHASE(projection);
        ++stats.projections;
        const auto& p=primitives[n.o][n.v][action];
        Intervals departures{{n.lo,std::min(n.hi,horizon-p.duration)}};
        if(departures[0].first>departures[0].second) return;
        for(const auto& t:p.touches) {
            int r=n.r+t.dr,c=n.c+t.dc;
            if(!inside(r,c) || grid[r][c]=='#') return;
            Intervals forbidden;
            for(auto [a,b]:blocked[cell(r,c)]) forbidden.push_back({a-t.last,b-t.first});
            departures=subtract(departures,normalize(forbidden));
            if(departures.empty()) return;
        }
        for(auto [a,b]:departures) {
            int r=n.r+p.dr,c=n.c+p.dc,lo=a+p.duration,hi=b+p.duration;
            if(p.velocity==0) hi=safe_end(r,c,hi);
            push({r,c,p.orientation,p.velocity,lo,hi,parent,action,a,b});
        }
    }
    std::pair<std::string,int> search() {
        int end=safe_end(sr,sc,start);
        if(end<start || grid[sr][sc]=='#') return {"invalid_start",-1};
        push({sr,sc,so,sv,start,sv==0?end:start,-1,-1,0,0});
        while(!open.empty()) {
            Entry entry; { PROFILE_PHASE(queue); entry=open.top(); open.pop(); } ++stats.pops;
            int id=std::get<3>(entry); Node n=nodes[id];
            auto remaining=subtract({{n.lo,n.hi}},closed[key(n)]);
            if(remaining.empty()) continue;
            if(remaining.size()!=1 || remaining[0]!=Interval{n.lo,n.hi}) {
                for(auto [a,b]:remaining) { Node trimmed=n; trimmed.lo=a; trimmed.hi=b; push(trimmed); }
                continue;
            }
            // A pending goal can be accepted even when the expansion budget is exhausted.
            if(n.r==gr && n.c==gc && n.v==gv) return {"solved",id};
            if(stats.expansions>=limit) return {"expansion_limit",-1};
#ifdef SIPP_WITNESS_AUDIT
            auto expansion_start=Clock::now();
#endif
            ++stats.expansions;
            auto& coverage=closed[key(n)]; coverage.push_back({n.lo,n.hi}); coverage=normalize(coverage);
            for(int a=0;a<static_cast<int>(primitives[n.o][n.v].size());++a) project(n,id,a);
#ifdef SIPP_WITNESS_AUDIT
            trace.push_back({key(n),n.lo,n.hi,std::chrono::duration<double,std::micro>(Clock::now()-expansion_start).count()});
#endif
        }
        return {"no_path",-1};
    }
    std::vector<Step> reconstruct(int goal) const {
        std::vector<Step> reverse_steps;
        int id=goal,t=nodes[goal].lo;
        while(nodes[id].parent!=-1) {
            const auto& n=nodes[id]; const auto& parent=nodes[n.parent];
            const auto& p=primitives[parent.o][parent.v][n.action];
            int departure=std::min(n.dep_hi,t-p.duration),arrival=departure+p.duration;
            if(departure<n.dep_lo || departure<parent.lo || departure>parent.hi)
                throw std::runtime_error("broken projection provenance");
            if(arrival<t) reverse_steps.push_back({"wait",n.r,n.c,n.o,n.v,arrival,t,n.r,n.c,n.o,n.v});
            reverse_steps.push_back({p.name,parent.r,parent.c,parent.o,parent.v,departure,arrival,n.r,n.c,n.o,n.v});
            t=departure; id=n.parent;
        }
        if(t>start) reverse_steps.push_back({"wait",sr,sc,so,sv,start,t,sr,sc,so,sv});
        std::reverse(reverse_steps.begin(),reverse_steps.end()); return reverse_steps;
    }
};
inline double elapsed(Clock::time_point a,Clock::time_point b) { return std::chrono::duration<double,std::micro>(b-a).count(); }
struct FreshSolution { int cost=-1; std::vector<Step> steps; };
inline void run_fresh(std::unique_ptr<Planner> planner, Clock::time_point begin, bool adaptive=false,double decision_us=0, FreshSolution* saved=nullptr) {
    auto& p=*planner;
    auto ready=Clock::now(); auto [status,goal]=p.search(); auto searched=Clock::now();
    auto steps=goal<0?std::vector<Step>{}:p.reconstruct(goal); auto finished=Clock::now();
    int cost=goal<0?-1:p.nodes[goal].lo; auto stats=p.stats;
    if(saved) { saved->cost=cost; saved->steps=steps; }
    { PROFILE_PHASE(release); planner.reset(); } auto destroyed=Clock::now();
    std::cout<<"{";
    PROFILE_EMIT();
    if(adaptive) std::cout<<"\"strategy\":\"full_replan\",\"decision_us\":"<<decision_us<<",";
    std::cout<<"\"status\":\""<<status<<"\",\"cost_ticks\":";
    if(goal<0) std::cout<<"null"; else std::cout<<cost;
    std::cout<<",\"setup_us\":"<<elapsed(begin,ready)<<",\"search_us\":"<<elapsed(ready,searched)
             <<",\"reconstruction_us\":"<<elapsed(searched,finished)<<",\"teardown_us\":"<<elapsed(finished,destroyed)
             <<",\"total_us\":"<<elapsed(begin,destroyed)
             <<",\"expansions\":"<<stats.expansions<<",\"generated\":"<<stats.generated
             <<",\"projections\":"<<stats.projections<<",\"queue_pops\":"<<stats.pops
             <<",\"peak_open\":"<<stats.peak_open<<",\"steps\":[";
    bool comma=false;
    for(const auto& s:steps) {
        if(comma) std::cout<<',';
        comma=true;
        std::cout<<"{\"action\":\""<<s.action<<"\",\"from\":["<<s.r<<','<<s.c<<','<<s.o<<','<<s.v
                 <<"],\"to\":["<<s.nr<<','<<s.nc<<','<<s.no<<','<<s.nv<<"],\"start\":"<<s.begin<<",\"end\":"<<s.end<<'}';
    }
    std::cout<<"]}\n"<<std::flush;
}
