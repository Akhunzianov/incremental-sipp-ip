#include "fresh.hpp"
int main() {
    std::ios::sync_with_stdio(false);
    int h,w;
    while(std::cin>>h>>w) {
        PROFILE_RESET();
        auto begin=Clock::now(); auto planner=std::make_unique<Planner>(); auto& p=*planner; p.h=h; p.w=w;
        if(!(std::cin>>p.horizon>>p.sr>>p.sc>>p.so>>p.sv>>p.start>>p.gr>>p.gc>>p.gv>>p.limit)) return 2;
        if(h<=0 || w<=0 || h>1024 || w>1024 || p.horizon<0 || p.horizon>10000000 ||
           !p.inside(p.sr,p.sc) || !p.inside(p.gr,p.gc) || p.so<0 || p.so>3 ||
           p.sv<0 || p.sv>1 || p.gv<0 || p.gv>1 || p.start<0 || p.start>p.horizon || p.limit<0) return 2;
        p.grid.resize(h); for(auto& row:p.grid) { if(!(std::cin>>row) || static_cast<int>(row.size())!=w) return 2; }
        p.blocked.resize(h*w); p.closed.resize(h*w*8);
        int count; if(!(std::cin>>count) || count<0) return 2;
        for(int i=0;i<count;++i) {
            int r,c,a,b; if(!(std::cin>>r>>c>>a>>b) || !p.inside(r,c) || a<0 || a>b || b>p.horizon) return 2;
            p.blocked[p.cell(r,c)].push_back({a,b});
        }
        for(auto& blocks:p.blocked) blocks=normalize(blocks);
        run_fresh(std::move(planner),begin);
    }
    return std::cin.eof()?0:2;
}
